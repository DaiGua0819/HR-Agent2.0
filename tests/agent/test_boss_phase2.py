"""Phase 2：BOSS 平台与共享 agent 流程测试。

全部用 FakePage、内存规则和假 LLM，不连接 DB，也不依赖真实浏览器登录态。
"""

from __future__ import annotations

import asyncio

from app.agent.graph import build_recruit_graph
from app.agent.proactive.thresholds import evaluate_proactive_threshold
from app.agent.runner import ConversationRunner
from app.browser.fake_page import FakePage
from app.core.constants import Platform
from app.evaluation.decision_log import InMemoryDecisionSink
from app.platforms.boss import actions as boss_actions
from app.platforms.boss.adapter import BossAdapter
from app.platforms.zhilian.adapter import ZhilianAdapter


class FakeLLM:
    """测试用结构化判断模型。"""

    def __init__(self, status: str) -> None:
        self.status = status

    async def judge(self, payload: dict[str, object]) -> dict[str, str]:
        _ = payload
        return {"status": self.status}


class TextOnlyPage:
    """只触发 BOSS 简历状态文本 fallback 的页面桩。"""

    def __init__(self, body: str) -> None:
        self.body = body

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        _ = script, arg
        return {}

    async def text(self, selector: str | None = None) -> str:
        _ = selector
        return self.body


class BossPreviewDownloadPage(FakePage):
    """Fake BOSS page where bytes appear only after clicking the preview download."""

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if script == "boss.resume_attachment_payload" or "boss_attachment_link" in script:
            return {"found": False}
        if "boss_attachment_preview" in script:
            self.current_conversation()["preview_opened"] = True
            return {"clicked": True, "source": "fake_boss_preview"}
        if "boss_attachment_download" in script:
            return {"clicked": True, "source": "fake_boss_preview_download"}
        return await super().eval_js(script, arg)


def test_same_graph_and_runner_support_zhilian_and_boss() -> None:
    """同一张图和同一个 runner 类可分别注入智联/BOSS adapter。"""

    graph = build_recruit_graph()
    for platform in (Platform.ZHILIAN, Platform.BOSS):
        state = asyncio.run(
            graph.ainvoke(
                {
                    "platform": platform.value,
                    "applied_position": "销售管培生",
                    "candidate": {"applied_position": "销售管培生"},
                    "rules": sample_rules(),
                },
                config={"configurable": {"thread_id": f"phase2-{platform.value}"}},
            )
        )
        assert state["stage"] == "rules_loaded"
        assert state["position_rule"]["category"] == "sales"

    zhilian_state, _ = run_case(
        Platform.ZHILIAN,
        conversation("销售管培生", [{"sender": "other", "text": "你好"}]),
    )
    boss_state, _ = run_case(
        Platform.BOSS,
        conversation("销售管培生", [{"sender": "other", "text": "你好"}]),
    )
    assert zhilian_state["next_action"] == boss_state["next_action"] == "ask_screening"


def test_boss_operation_direct_resume_sends_prephrase_before_request() -> None:
    """BOSS 运营 A/B 先发“可以发一份简历过来吗”，再执行求简历。"""

    state, page = run_case(
        Platform.BOSS,
        conversation("运营A", [{"sender": "other", "text": "你好"}]),
    )
    assert state["next_action"] == "request_resume"
    assert page.sent_messages == ["可以发一份简历过来吗"]
    assert page.resume_requests == 1

    _, zhilian_page = run_case(
        Platform.ZHILIAN,
        conversation("运营A", [{"sender": "other", "text": "你好"}]),
    )
    assert zhilian_page.sent_messages == []
    assert zhilian_page.resume_requests == 1


def test_boss_direct_resume_position_question_still_requests_resume() -> None:
    """BOSS 直求简历岗位：带问句也不升级未知问题，直接求简历。"""

    state, page = run_case(
        Platform.BOSS,
        conversation(
            "投资交易策略研究员（量化与市场情绪方向）",
            [{"sender": "other", "text": "可否进一步沟通呢？"}],
        ),
    )

    assert state["next_action"] == "request_resume"
    assert state["stage"] == "direct_resume"
    assert page.sent_messages == ["你好，方便发一份简历过来吗"]
    assert page.resume_requests == 1


def test_boss_direct_resume_unknown_job_detail_question_escalates() -> None:
    """Direct-resume jobs do not bypass unknown job-detail questions."""

    state, page = run_case(
        Platform.BOSS,
        conversation("DirectRole", [{"sender": "other", "text": "What are the job details?"}]),
    )

    assert state["next_action"] == "escalate"
    assert state["stage"] == "unknown_question"
    assert page.sent_messages == []
    assert page.resume_requests == 0


def test_boss_ai_intern_sends_company_info_then_requests_resume() -> None:
    """BOSS AI 应用开发岗位：先走公司基本情况常用语，接受后求简历。"""

    state, page = run_case(
        Platform.BOSS,
        conversation("AI应用开发实习生", [{"sender": "other", "text": "你好"}]),
    )
    assert state["next_action"] == "ask_basic_conditions"
    assert page.sent_messages == ["基础条件确认话术"]

    state, page = run_case(
        Platform.BOSS,
        conversation(
            "AI应用开发实习生",
            [
                {"sender": "me", "text": "基础条件确认话术"},
                {"sender": "other", "text": "可以接受"},
            ],
        ),
        llm=FakeLLM("accept"),
    )
    assert state["next_action"] == "request_resume"
    assert page.resume_requests == 1


def test_boss_ai_intern_initial_phrase_precedes_questions() -> None:
    """BOSS AI 应用开发：未发基础条件前，候选人提问也先发基础条件。"""

    state, page = run_case(
        Platform.BOSS,
        conversation(
            "AI应用开发实习生",
            [{"sender": "other", "text": "方便看看我的简历吗"}],
        ),
    )

    assert state["next_action"] == "ask_basic_conditions"
    assert state["stage"] == "basic_phrase_sent"
    assert page.sent_messages == ["基础条件确认话术"]


def test_boss_ai_intern_attachment_after_basic_phrase_is_received() -> None:
    """BOSS AI 应用开发：基础条件已发后收到附件简历，直接等待不再判不明确。"""

    convo = conversation(
        "AI应用开发实习生",
        [
            {"sender": "me", "text": "基础条件确认话术"},
            {"sender": "other", "text": "简历_AI应用开发.pdf"},
        ],
    )
    convo["has_resume_attachment"] = True

    state, page = run_case(Platform.BOSS, convo)

    assert state["next_action"] == "wait"
    assert state["stage"] == "resume_attachment_received"
    assert state["decision"]["result"]["reason"] == "boss_attachment_present_no_local_download"
    assert page.resume_requests == 0


def test_boss_resume_state_ignores_sidebar_resume_buttons() -> None:
    """BOSS：右侧“在线简历/附件简历”按钮不等于候选人已发简历。"""

    page = TextOnlyPage("牛人资料 在线简历 附件简历 求简历 电话 微信")
    state = asyncio.run(boss_actions.inspect_resume_request_state(page))  # type: ignore[arg-type]
    assert not state.has_resume_attachment
    assert not state.already_requested


def test_boss_resume_state_detects_chat_file_attachment() -> None:
    """BOSS：聊天消息区出现文件名时仍识别为已有简历。"""

    page = TextOnlyPage("聊天消息 09:30 张三简历.pdf 预览 下载")
    state = asyncio.run(boss_actions.inspect_resume_request_state(page))  # type: ignore[arg-type]
    assert state.has_resume_attachment


def test_boss_existing_attachment_does_not_download_locally() -> None:
    """BOSS existing attachments are not downloaded locally."""

    page = FakePage(
        conversations=[
            {
                "id": "boss-attachment",
                "name": "Candidate",
                "position": "DirectRole",
                "label": "Candidate DirectRole",
                "latest_message": "resume.pdf",
                "unread_count": 1,
                "messages": [{"sender": "other", "text": "resume.pdf"}],
                "has_resume_attachment": True,
                "resume_bytes": b"%PDF-1.7\nboss\n%%EOF",
                "resume_filename": "candidate.pdf",
            }
        ]
    )

    result = asyncio.run(boss_actions.request_resume(page))

    assert result["resumeReceived"] is True
    assert result["downloaded"] is False
    assert result["reason"] == "boss_attachment_present_no_local_download"


def test_boss_existing_attachment_does_not_open_preview_download() -> None:
    """BOSS should not click preview/download for existing attachments."""

    page = BossPreviewDownloadPage(
        conversations=[
            {
                "id": "boss-preview-attachment",
                "name": "Preview Candidate",
                "position": "DirectRole",
                "label": "Preview Candidate DirectRole",
                "latest_message": "点击预览附件简历",
                "unread_count": 1,
                "messages": [{"sender": "other", "text": "点击预览附件简历"}],
                "has_resume_attachment": True,
                "resume_bytes": b"%PDF-1.7\nboss preview\n%%EOF",
                "resume_filename": "preview-candidate.pdf",
            }
        ]
    )

    result = asyncio.run(boss_actions.request_resume(page))

    assert result["resumeReceived"] is True
    assert result["downloaded"] is False
    assert result["reason"] == "boss_attachment_present_no_local_download"
    assert "preview_opened" not in page.current_conversation()


def test_boss_resume_state_detects_request_sent_system_message() -> None:
    """BOSS：系统消息“简历请求已发送”表示求简历已经成功。"""

    page = TextOnlyPage("聊天消息 09:31 送达 可以发一份简历过来吗 简历请求已发送")
    state = asyncio.run(boss_actions.inspect_resume_request_state(page))  # type: ignore[arg-type]
    assert state.already_requested


def test_boss_unread_list_requires_numeric_badge() -> None:
    """BOSS：只有带数字未读徽标的行才进入未读处理队列。"""

    page = FakePage(
        conversations=[
            {
                "id": "already-read",
                "name": "已处理",
                "position": "AI应用开发实习生",
                "label": "已处理 AI应用开发实习生",
                "unread_count": 0,
            },
            {
                "id": "new-unread",
                "name": "新未读",
                "position": "投资交易策略研究员",
                "label": "新未读 投资交易策略研究员",
                "unread_count": 2,
            },
        ]
    )

    refs = asyncio.run(boss_actions.read_unread_conversations(page, owner="宋峰峰"))

    assert [item.conversation_id for item in refs] == ["new-unread"]


def test_boss_screening_ask_accept_and_reject() -> None:
    """BOSS 岗位筛选：未问发问题，通过求简历，不满足跳过。"""

    state, page = run_case(
        Platform.BOSS,
        conversation("销售管培生", [{"sender": "other", "text": "你好"}]),
    )
    assert state["next_action"] == "ask_screening"
    assert page.sent_messages == ["你是否接受出差？"]

    state, page = run_case(
        Platform.BOSS,
        conversation(
            "销售管培生",
            [
                {"sender": "me", "text": "你是否接受出差？"},
                {"sender": "other", "text": "可以接受"},
            ],
        ),
    )
    assert state["next_action"] == "request_resume"
    assert page.resume_requests == 1

    state, page = run_case(
        Platform.BOSS,
        conversation(
            "销售管培生",
            [
                {"sender": "me", "text": "你是否接受出差？"},
                {"sender": "other", "text": "不能出差"},
            ],
        ),
    )
    assert state["next_action"] == "skip"
    assert page.resume_requests == 0


def test_proactive_thresholds_cover_core_positions() -> None:
    """主动联系门槛：HR、销售、电气等典型岗位通过/跳过。"""

    assert evaluate_proactive_threshold("24岁 本科 人力资源管理", "HRBP").passed
    assert not evaluate_proactive_threshold("24岁 本科 市场营销", "HRBP").passed
    assert evaluate_proactive_threshold("24岁 大专 销售经验", "销售管培生").passed
    assert not evaluate_proactive_threshold("26岁 大专 销售经验", "销售管培生").passed
    assert evaluate_proactive_threshold("30岁 本科 电气工程 PLC 项目", "电气工程师").passed
    assert not evaluate_proactive_threshold("30岁 本科 电气工程", "电气工程师").passed
    assert not evaluate_proactive_threshold("本科 电气工程 PLC 项目", "电气工程师").passed


def test_boss_proactive_greet_uses_fake_page_and_thresholds() -> None:
    """BOSS 推荐牛人：假页面打开弹层、过门槛后只点 btn-greet。"""

    page = FakePage(
        selected_recommend_position="电气工程师",
        recommend_candidates=[
            {
                "name": "候选A",
                "card_text": "30岁 本科 电气工程",
                "resume_text": "自动化产线 PLC 项目经验",
            },
            {
                "name": "候选B",
                "card_text": "30岁 本科 电气工程",
                "resume_text": "缺少控制器证据",
            },
        ],
    )
    adapter = BossAdapter(page, owner="和新红")
    result = asyncio.run(adapter.proactive_greet("电气工程师"))
    assert result["greeted"] == 1
    assert page.proactive_greets == ["候选A"]


def run_case(
    platform: Platform,
    convo: dict[str, object],
    llm: FakeLLM | None = None,
):
    """按平台运行单条会话。"""

    page = FakePage(conversations=[convo])
    adapter = (
        BossAdapter(page, owner="和新红")
        if platform == Platform.BOSS
        else ZhilianAdapter(page, owner="宋峰峰")
    )
    sink = InMemoryDecisionSink()
    runner = ConversationRunner(adapter, rules=sample_rules(), llm=llm, decision_sink=sink)
    state = asyncio.run(runner.run_current())
    assert sink.events
    return state, page


def conversation(position: str, messages: list[dict[str, str]]) -> dict[str, object]:
    """构造 FakePage 会话。"""

    return {
        "id": f"conv-{position}",
        "name": "候选人",
        "position": position,
        "label": f"候选人 {position}",
        "latest_message": messages[-1]["text"],
        "unread_count": 1,
        "messages": messages,
    }


def sample_rules() -> dict[str, object]:
    """测试用最小规则库。"""

    return {
        "positionReplies": {
            "AI应用开发实习生": {
                "category": "ai_app_intern",
                "initialCommonPhrase": "基础条件确认话术",
            },
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
            "投资交易策略研究员（量化与市场情绪方向）": {
                "category": "investment_direct_resume",
                "directResume": True,
                "resumeJobType": "投资交易策略研究员",
                "resumeRequestPrompt": "你好，方便发一份简历过来吗",
            },
            "DirectRole": {
                "category": "direct",
                "directResume": True,
                "resumeJobType": "DirectRole",
                "resumeRequestPrompt": "please send resume",
            },
        },
        "companyKnowledgeBase": {},
    }
