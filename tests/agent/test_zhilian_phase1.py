"""Phase 1 智联竖切验收测试。

全部测试使用 FakePage 和内存规则，不依赖真实浏览器、真实登录态或真实 DB。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agent.runner import ZhilianConversationRunner
from app.browser.fake_page import FakePage
from app.domain.conversation.repository import ConversationRepository
from app.evaluation.decision_log import InMemoryDecisionSink
from app.platforms.zhilian import selectors
from app.platforms.zhilian.actions import (
    _state_matches_context,
    find_next_unread_thread,
    inspect_resume_request_state,
    read_unread_conversations,
    read_unread_row_states,
    request_resume,
    select_unread_filter,
    send_message,
)
from app.platforms.zhilian.adapter import ZhilianAdapter


class FakeLLM:
    """测试用结构化判断模型。"""

    def __init__(self, status: str) -> None:
        self.status = status

    async def judge(self, payload: dict[str, object]) -> dict[str, str]:
        _ = payload
        return {"status": self.status}


class TextOnlyPage:
    """Minimal page for Zhilian resume-state fallback tests."""

    def __init__(self, body: str) -> None:
        self.body = body

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        _ = script, arg
        return {}

    async def text(self, selector: str | None = None) -> str:
        _ = selector
        return self.body


def test_ai_basic_flow_send_accept_reject_and_unclear() -> None:
    """AI 应用岗位：未发基础条件、接受、拒绝和模糊都按规则推进。"""

    state, page = run_case(conversation("AI应用开发实习生", [{"sender": "other", "text": "你好"}]))
    assert state["next_action"] == "ask_basic_conditions"
    assert page.sent_messages == ["基础条件确认话术"]

    state, page = run_case(
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

    for reply in ["不接受单休", "我再想想"]:
        state, page = run_case(
            conversation(
                "AI应用开发实习生",
                [
                    {"sender": "me", "text": "基础条件确认话术"},
                    {"sender": "other", "text": reply},
                ],
            )
        )
        assert state["next_action"] == "wait"
        assert page.resume_requests == 0


def test_sales_screening_flow_ask_accept_and_reject() -> None:
    """销售岗位：未问发岗位问题，通过求简历，不满足跳过。"""

    state, page = run_case(conversation("销售管培生", [{"sender": "other", "text": "你好"}]))
    assert state["next_action"] == "ask_screening"
    assert page.sent_messages == ["你是否接受出差？"]

    state, page = run_case(
        conversation(
            "销售管培生",
            [
                {"sender": "me", "text": "你是否接受出差？"},
                {"sender": "other", "text": "可以接受"},
            ],
        )
    )
    assert state["next_action"] == "request_resume"
    assert page.resume_requests == 1

    state, page = run_case(
        conversation(
            "销售管培生",
            [
                {"sender": "me", "text": "你是否接受出差？"},
                {"sender": "other", "text": "不能出差"},
            ],
        )
    )
    assert state["next_action"] == "skip"
    assert page.resume_requests == 0


def test_operation_direct_resume_has_no_prompt() -> None:
    """运营 A/B 在智联不发前置话术，直接要附件简历。"""

    state, page = run_case(conversation("运营A", [{"sender": "other", "text": "你好"}]))
    assert state["next_action"] == "request_resume"
    assert page.sent_messages == []
    assert page.resume_requests == 1

    state, page = run_case(conversation("外部财务产品顾问", [{"sender": "other", "text": "你好"}]))
    assert state["next_action"] == "request_resume"
    assert page.sent_messages == ["你好，方便发一份简历过来吗"]
    assert page.resume_requests == 1


def test_zhilian_unread_filter_and_refs_use_shared_pattern() -> None:
    """智联未读筛选校验 active，未读引用只返回真实未读会话。"""

    page = FakePage(
        conversations=[
            {
                **conversation("销售管培生", [{"sender": "other", "text": "你好"}]),
                "unread_count": 0,
            },
            conversation("电气工程师", [{"sender": "other", "text": "你好"}]),
        ]
    )
    result = asyncio.run(select_unread_filter(page))
    refs = asyncio.run(read_unread_conversations(page, owner="宋峰峰"))
    assert result["selected"] is True
    assert [item.conversation_id for item in refs] == ["conv-电气工程师"]


def test_zhilian_unread_rows_exclude_read_and_system_labels() -> None:
    """Only rows with a real unread badge and no read/system label are actionable."""

    page = FakePage(
        conversations=[
            {
                **conversation("SalesRole", [{"sender": "other", "text": "hello"}]),
                "id": "read-row",
                "label": "Alice [已读] SalesRole",
                "unread_count": 2,
            },
            {
                **conversation("SalesRole", [{"sender": "other", "text": "hello"}]),
                "id": "system-row",
                "label": "平台推荐 SalesRole",
                "unread_count": 1,
            },
            {
                **conversation("SalesRole", [{"sender": "other", "text": "hello"}]),
                "id": "real-unread",
                "name": "Bob",
                "label": "Bob SalesRole",
                "unread_count": 1,
            },
        ]
    )

    rows = asyncio.run(read_unread_row_states(page))
    ref = asyncio.run(find_next_unread_thread(page, owner="owner"))

    assert [row["id"] for row in rows] == ["real-unread"]
    assert ref is not None
    assert ref.conversation_id == "real-unread"


def test_zhilian_identity_requires_name_when_available() -> None:
    """同岗位多候选人时，不能只靠岗位相同误判打开成功。"""

    state = {"label": "文成 AI应用开发实习生", "position": "AI应用开发实习生"}

    assert not _state_matches_context(
        state,
        {"name": "杜智", "position": "AI应用开发实习生"},
    )
    assert _state_matches_context(
        state,
        {"name": "文成", "position": "AI应用开发实习生"},
    )


def test_zhilian_request_resume_state_and_confirm() -> None:
    """智联求附件简历：已收/已求跳过，未求过则点击并确认。"""

    received = FakePage(
        conversations=[
            {
                **conversation("销售管培生", [{"sender": "other", "text": "你好"}]),
                "has_resume_attachment": True,
            }
        ]
    )
    received_result = asyncio.run(request_resume(received))
    assert received_result["resumeReceived"] is True
    assert received.resume_requests == 0

    requested = FakePage(
        conversations=[
            {
                **conversation("销售管培生", [{"sender": "other", "text": "你好"}]),
                "resume_requested": True,
            }
        ]
    )
    requested_result = asyncio.run(request_resume(requested))
    assert requested_result["skipped"] is True
    assert requested.resume_requests == 0

    page = FakePage(
        conversations=[conversation("销售管培生", [{"sender": "other", "text": "你好"}])]
    )
    result = asyncio.run(request_resume(page))
    assert result["requested"] is True
    assert result["confirmed"] is True
    assert page.resume_requests == 1


def test_zhilian_request_resume_does_not_require_confirm_dialog() -> None:
    """智联点击“要附件简历”后无确认弹窗，点击成功即视为请求已发出。"""

    page = FakePage(
        conversations=[
            {
                **conversation("SalesRole", [{"sender": "other", "text": "hello"}]),
                "visible_request_resume_confirm": False,
            }
        ]
    )

    result = asyncio.run(request_resume(page))

    assert result["requested"] is True
    assert result["confirmed"] is True
    assert result["verifyReason"] == "no_confirm_required"
    assert page.resume_requests == 1
    assert page.current_conversation().get("resume_request_confirmed") is not True


def test_zhilian_request_resume_downloads_attachment_after_request() -> None:
    """点击要附件简历后出现“查看附件简历”时，应继续下载附件简历。"""

    page = ZhilianAttachmentAfterRequestPage(
        conversations=[
            {
                **conversation(
                    "企业内容运营负责人（B2B/短视频方向）",
                    [{"sender": "other", "text": "你好"}],
                ),
                "visible_request_resume_confirm": False,
                "zhilian_attachment_bytes": b"%PDF-1.7\nbody\n%%EOF",
                "zhilian_attachment_filename": "李江春_企业内容运营负责人.pdf",
            }
        ]
    )

    result = asyncio.run(request_resume(page))

    assert result["requested"] is True
    assert result["resumeReceived"] is True
    assert result["downloaded"] is True
    assert result["sourceKind"] == "attachment"
    assert page.current_conversation()["zhilian_view_attachment_clicked"] is True


def test_zhilian_send_message_records_enter_send_action() -> None:
    """Enter 发送成功时也要进入 reliable_actions，方便 live summary 证明已发送。"""

    page = FakePage(
        conversations=[conversation("AI应用开发实习生", [{"sender": "other", "text": "你好"}])]
    )

    result = asyncio.run(send_message(page, "基础条件确认话术"))

    assert result.sent is True
    assert result.verified is True
    assert any(
        action.get("action") == "press" and action.get("label") == "智联输入框 Enter 发送"
        for action in page.reliable_actions
    )


def test_zhilian_resume_state_does_not_treat_request_button_as_received() -> None:
    """The request button is not evidence that an attachment was received."""

    request_button = asyncio.run(
        inspect_resume_request_state(TextOnlyPage(selectors.REQUEST_RESUME_TEXT))  # type: ignore[arg-type]
    )
    assert request_button.has_resume_attachment is False
    assert request_button.already_requested is False

    view_attachment = asyncio.run(
        inspect_resume_request_state(TextOnlyPage(selectors.ATTACHMENT_VIEW_TEXT))  # type: ignore[arg-type]
    )
    assert view_attachment.has_resume_attachment is True

    file_name = asyncio.run(
        inspect_resume_request_state(TextOnlyPage("candidate_resume.pdf"))  # type: ignore[arg-type]
    )
    assert file_name.has_resume_attachment is True

    requested = asyncio.run(
        inspect_resume_request_state(
            TextOnlyPage("\u5df2\u5411\u5bf9\u65b9\u8981\u9644\u4ef6\u7b80\u5386")
        )  # type: ignore[arg-type]
    )
    assert requested.has_resume_attachment is False
    assert requested.already_requested is True


def test_knowledge_answer_and_unknown_question_escalation() -> None:
    """知识库命中则回答，未命中则不回复并转人工记录。"""

    state, page = run_case(conversation("销售管培生", [{"sender": "other", "text": "薪资多少？"}]))
    assert state["next_action"] == "answer_question"
    assert page.sent_messages == ["薪资以岗位说明为准。"]

    state, page = run_case(
        conversation("销售管培生", [{"sender": "other", "text": "住宿政策是什么？"}])
    )
    assert state["next_action"] == "escalate"
    assert state["pending_question"] == "住宿政策是什么？"
    assert page.sent_messages == []


def test_send_message_verification_uses_recent_mine_message_selector() -> None:
    """发送后校验最近己方消息，保留智联 mine 选择器对照。"""

    assert "div.message-item.mine" in selectors.MINE_MESSAGE
    page = FakePage(
        conversations=[conversation("销售管培生", [{"sender": "other", "text": "你好"}])]
    )
    result = asyncio.run(send_message(page, "收到"))
    assert result.sent is True
    assert result.verified is True
    assert page.sent_messages == ["收到"]


def test_send_failure_does_not_persist_asked_question(tmp_path: Path) -> None:
    """If fill succeeds but send verification fails, do not persist asked_questions."""

    repository = ConversationRepository(tmp_path / "send-failed.sqlite")
    page = FakePage(
        conversations=[
            {
                **conversation("SalesRole", [{"sender": "other", "text": "hello"}]),
                "send_fails": True,
            }
        ]
    )
    adapter = ZhilianAdapter(page, owner="owner", dry_run=False)
    runner = ZhilianConversationRunner(
        adapter,
        rules={
            "positionReplies": {
                "SalesRole": {
                    "category": "sales",
                    "screeningQuestions": ["Do you accept travel?"],
                }
            },
            "companyKnowledgeBase": {},
        },
        conversation_repository=repository,
    )

    state = asyncio.run(runner.run_current())
    status = repository.get_status(str(state["session_id"]))

    assert state["next_action"] == "send_failed"
    assert state["stage"] == "screening_question_send_failed"
    assert status.asked_questions == []


def run_case(convo: dict[str, object], llm: FakeLLM | None = None):
    """运行单条会话并返回 state 与 fake page。"""

    page = FakePage(conversations=[convo])
    adapter = ZhilianAdapter(page, owner="宋峰峰")
    sink = InMemoryDecisionSink()
    runner = ZhilianConversationRunner(adapter, rules=sample_rules(), llm=llm, decision_sink=sink)
    state = asyncio.run(runner.run_current())
    assert sink.events
    return state, page


class ZhilianAttachmentAfterRequestPage(FakePage):
    """Fake 智联页：点击要附件后生成可下载的查看附件简历卡片。"""

    async def handle_element_click(self, element):  # type: ignore[no-untyped-def]
        await super().handle_element_click(element)
        if "要附件简历" in element.text_value:
            convo = self.current_conversation()
            convo["has_resume_attachment"] = True
            convo["resume_requested"] = True

    async def click_and_download(
        self,
        script: str,
        arg: object | None = None,
        timeout_ms: int = 15000,
    ) -> dict[str, object]:
        _ = arg, timeout_ms
        if "zhilian_view_attachment_resume_download" not in script:
            return await super().click_and_download(script, arg, timeout_ms)
        convo = self.current_conversation()
        convo["zhilian_view_attachment_clicked"] = True
        return {
            "ok": True,
            "clicked": {"clicked": True, "source": "fake_zhilian_attachment"},
            "filename": convo.get("zhilian_attachment_filename", "zhilian_resume.pdf"),
            "bytes": convo.get("zhilian_attachment_bytes"),
            "path": "",
        }


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
        },
        "companyKnowledgeBase": {
            "faq": [
                {
                    "question": "薪资",
                    "answer": "薪资以岗位说明为准。",
                }
            ]
        },
    }
