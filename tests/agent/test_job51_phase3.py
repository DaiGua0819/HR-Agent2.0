"""Phase 3：51job 平台接入测试。

全部测试使用 FakePage、内存规则和内存下载记忆，不接 DB、不依赖真实浏览器。
"""

from __future__ import annotations

import asyncio

from app.agent.graph import build_recruit_graph
from app.agent.runner import ConversationRunner
from app.browser.fake_page import FakePage
from app.core.constants import Platform
from app.evaluation.decision_log import InMemoryDecisionSink
from app.platforms.job51.actions_chat import (
    find_next_thread,
    read_unread_conversations,
    should_skip_thread_label,
    verify_opened_candidate,
)
from app.platforms.job51.actions_resume import (
    InMemoryResumeDownloadMemory,
    resume_download_suitability_guard,
    save_resume_bytes,
    validate_resume_bytes,
)
from app.platforms.job51.adapter import Job51Adapter


def test_job51_reuses_shared_graph_and_runner() -> None:
    """51job 注入同一张图和同一个 ConversationRunner，跑通筛选问题。"""

    graph = build_recruit_graph()
    state = asyncio.run(
        graph.ainvoke(
            {
                "platform": Platform.JOB51.value,
                "applied_position": "销售管培生",
                "candidate": {"applied_position": "销售管培生"},
                "rules": sample_rules(),
            },
            config={"configurable": {"thread_id": "phase3-job51"}},
        )
    )
    assert state["stage"] == "rules_loaded"

    state, page = run_case(
        conversation("销售管培生", [{"sender": "other", "text": "你好"}])
    )
    assert state["next_action"] == "ask_screening"
    assert page.sent_messages == ["你是否接受出差？"]


def test_job51_skip_rules_do_not_repeat_replied_or_platform_rows() -> None:
    """[送达]/[已读]/[平台推荐] 会话行被跳过，避免重复回复。"""

    assert should_skip_thread_label("张三 [送达] 销售管培生")
    assert should_skip_thread_label("李四 [已读] 电气工程师")
    assert should_skip_thread_label("[平台推荐] 以下是为你推荐的人才")
    page = FakePage(
        conversations=[
            conversation(
                "销售管培生",
                [{"sender": "other", "text": "已回复"}],
                label="张三 [送达]",
            ),
            conversation("电气工程师", [{"sender": "other", "text": "已读"}], label="李四 [已读]"),
            conversation("HRBP", [{"sender": "other", "text": "推荐"}], label="[平台推荐]"),
            conversation("销售管培生", [{"sender": "other", "text": "你好"}], label="王五"),
        ]
    )
    refs = asyncio.run(read_unread_conversations(page, owner="和新红"))
    assert [item.conversation_id for item in refs] == ["conv-销售管培生"]


def test_job51_find_next_thread_verifies_opened_candidate() -> None:
    """51job 点开未读行后校验当前聊天区身份，避免虚拟列表误读上一个人。"""

    page = FakePage(
        conversations=[
            conversation("销售管培生", [{"sender": "other", "text": "你好"}], label="候选人A"),
            conversation("电气工程师", [{"sender": "other", "text": "你好"}], label="候选人B"),
        ]
    )
    ref = asyncio.run(find_next_thread(page, owner="和新红"))
    assert ref is not None
    assert ref.conversation_id == "conv-销售管培生"
    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {"label": "候选人A", "name": "候选人", "position": "销售管培生"},
            chat_ready=True,
        )
    )
    assert opened["opened"] is True


def test_job51_operation_no_prephrase_and_finance_has_prompt() -> None:
    """运营 A/B 在 51job 不发前置话术；财务 AI 直求简历会发配置话术。"""

    _, page = run_case(conversation("运营A", [{"sender": "other", "text": "你好"}]))
    assert page.sent_messages == []
    assert page.resume_requests == 1

    _, page = run_case(
        conversation("外部财务产品顾问", [{"sender": "other", "text": "你好"}])
    )
    assert page.sent_messages == ["你好，方便发一份简历过来吗"]
    assert page.resume_requests == 1


def test_job51_resume_validation_and_memory_guard() -> None:
    """真实 PDF/docx 通过；预览文字/伪 PDF 拒绝；同哈希去重；候选人缺失拦截。"""

    pdf = b"%PDF-1.7\nbody\n%%EOF"
    docx = b"PK\x03\x04[Content_Types].xml"
    assert validate_resume_bytes(pdf).ok
    assert validate_resume_bytes(docx).ok
    assert not validate_resume_bytes("在线简历预览文字".encode()).ok
    assert not validate_resume_bytes(b"%PDF-1.7\nmissing eof").ok
    assert resume_download_suitability_guard("", "销售管培生")["blocked"] is True

    memory = InMemoryResumeDownloadMemory()
    first = save_resume_bytes(
        pdf,
        candidate_name="王五",
        applied_position="销售管培生",
        memory=memory,
    )
    second = save_resume_bytes(
        pdf,
        candidate_name="王五",
        applied_position="销售管培生",
        memory=memory,
    )
    assert first["downloaded"] is True
    assert second["duplicate"] is True


def test_job51_request_resume_rejects_preview_only() -> None:
    """聊天里可见的在线简历预览文字不能被计为已下载简历。"""

    page = FakePage(
        conversations=[
            conversation(
                "销售管培生",
                [{"sender": "other", "text": "已发在线简历"}],
                preview_only=True,
            )
        ]
    )
    adapter = Job51Adapter(page, owner="和新红")
    result = asyncio.run(adapter.request_resume())
    assert result["requested"] is True
    assert result["confirmed"] is True
    assert result["downloaded"] is False
    assert result["reason"] == "preview_only_rejected"
    assert page.resume_requests == 1


def test_job51_proactive_uses_shared_thresholds_and_mode_switch() -> None:
    """51job 人才望远镜切回传统模式，跳过已看卡片，复用门槛后 Hi 聊。"""

    page = FakePage(
        selected_recommend_position="电气工程师",
        recommend_traditional_mode=False,
        recommend_candidates=[
            {
                "name": "已看候选",
                "card_text": "30岁 本科 电气工程 PLC",
                "viewed": True,
            },
            {
                "name": "候选A",
                "card_text": "30岁 本科 电气工程",
                "resume_text": "自动化 PLC 项目",
            },
            {
                "name": "候选B",
                "card_text": "30岁 本科 电气工程",
                "resume_text": "低压配电维护经验",
            },
        ],
    )
    adapter = Job51Adapter(page, owner="和新红")
    result = asyncio.run(adapter.proactive_greet("电气工程师"))
    assert page.recommend_traditional_mode is True
    assert result["greeted"] == 1
    assert page.proactive_greets == ["候选A"]
    assert any(item["reason"] == "already_viewed_badge" for item in result["skipped"])


def run_case(convo: dict[str, object]):
    """运行单条 51job 会话。"""

    page = FakePage(conversations=[convo])
    adapter = Job51Adapter(page, owner="和新红")
    sink = InMemoryDecisionSink()
    runner = ConversationRunner(adapter, rules=sample_rules(), decision_sink=sink)
    state = asyncio.run(runner.run_current())
    assert sink.events
    return state, page


def conversation(
    position: str,
    messages: list[dict[str, str]],
    *,
    label: str = "",
    preview_only: bool = False,
) -> dict[str, object]:
    """构造 FakePage 51job 会话。"""

    return {
        "id": f"conv-{position}",
        "name": "候选人",
        "position": position,
        "label": label or f"候选人 {position}",
        "latest_message": messages[-1]["text"],
        "unread_count": 1,
        "messages": messages,
        "preview_only": preview_only,
    }


def sample_rules() -> dict[str, object]:
    """测试用最小规则库。"""

    return {
        "positionReplies": {
            "销售管培生": {
                "category": "sales",
                "screeningQuestions": ["你是否接受出差？"],
            },
            "运营A": {
                "category": "operation_direct_resume",
                "directResume": True,
                "resumeJobType": "运营A",
                "resumeRequestPrompt": "可以发一份简历过来吗",
            },
            "外部财务产品顾问": {
                "category": "finance_ai_direct_resume",
                "directResume": True,
                "resumeJobType": "外部财务产品顾问",
                "resumeRequestPrompt": "你好，方便发一份简历过来吗",
            },
        },
        "companyKnowledgeBase": {},
    }
