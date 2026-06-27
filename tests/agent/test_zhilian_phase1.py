"""Phase 1 智联竖切验收测试。

全部测试使用 FakePage 和内存规则，不依赖真实浏览器、真实登录态或真实 DB。
"""

from __future__ import annotations

import asyncio

from app.agent.runner import ZhilianConversationRunner
from app.browser.fake_page import FakePage
from app.evaluation.decision_log import InMemoryDecisionSink
from app.platforms.zhilian import selectors
from app.platforms.zhilian.actions import (
    read_unread_conversations,
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


def run_case(convo: dict[str, object], llm: FakeLLM | None = None):
    """运行单条会话并返回 state 与 fake page。"""

    page = FakePage(conversations=[convo])
    adapter = ZhilianAdapter(page, owner="宋峰峰")
    sink = InMemoryDecisionSink()
    runner = ZhilianConversationRunner(adapter, rules=sample_rules(), llm=llm, decision_sink=sink)
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
