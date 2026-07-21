"""Phase 2：BOSS 平台与共享 agent 流程测试。

全部用 FakePage、内存规则和假 LLM，不连接 DB，也不依赖真实浏览器登录态。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agent.graph import build_recruit_graph
from app.agent.judgement import judge_candidate_reply
from app.agent.proactive.thresholds import evaluate_proactive_threshold
from app.agent.rules import (
    find_knowledge_answer,
    find_knowledge_answers,
    load_chat_rules,
    looks_like_question,
    select_position_rule,
)
from app.agent.runner import ConversationRunner
from app.agent.screening import analyze_position_screening
from app.browser.fake_page import FakeElement, FakePage
from app.core.constants import Platform
from app.evaluation.decision_log import InMemoryDecisionSink
from app.platforms.boss import actions as boss_actions
from app.platforms.boss import dom_scripts as boss_dom_scripts
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


class DelayedBossChatPage(FakePage):
    """Fake BOSS page whose chat UI appears only after wait_for is called."""

    def __init__(self) -> None:
        super().__init__(
            conversations=[
                {
                    "id": "delayed-unread",
                    "name": "延迟候选人",
                    "position": "AI应用开发实习生",
                    "label": "延迟候选人 AI应用开发实习生",
                    "unread_count": 1,
                }
            ]
        )
        self.chat_ready = False
        self.waited_selectors: list[str] = []

    async def query_all(self, selector: str):
        if not self.chat_ready and (
            "chat-message-filter" in selector
            or ".user-list-item" in selector
            or ".geek-item" in selector
        ):
            return []
        if self.chat_ready and "chat-message-filter" in selector:
            return [FakeElement(self, selector, "未读")]
        return await super().query_all(selector)

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if "chat_message_filter_left_span" in script:
            if not self.chat_ready:
                return {"selected": False, "reason": "unread_filter_not_found"}
            self.unread_selected = True
            return {"selected": True, "label": "未读", "source": "fake_boss_filter"}
        if (
            ".chat-message-filter-left span.active" in script
            and "chat_message_filter_left_span" not in script
        ):
            return "未读" if self.unread_selected else "全部"
        return await super().eval_js(script, arg)

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> bool:
        self.waited_selectors.append(selector)
        self.chat_ready = True
        return True

    async def handle_element_click(self, element) -> None:
        if "chat-message-filter" in element.selector:
            self.unread_selected = True
            return
        await super().handle_element_click(element)


class BossHardResumeActionPage(FakePage):
    """Fake BOSS page where only hard DOM function calls can request resumes."""

    def __init__(self, *, pending_resume_consent: bool = False) -> None:
        super().__init__(
            conversations=[
                {
                    "id": "hard-resume",
                    "name": "求简历候选人",
                    "position": "DirectRole",
                    "label": "求简历候选人 DirectRole",
                    "unread_count": 1,
                    "messages": [{"sender": "other", "text": "你好"}],
                }
            ]
        )
        self.pending_resume_consent = pending_resume_consent
        self.resume_button_clicked = False
        self.resume_confirm_clicked = False
        self.resume_consent_clicked = False
        self.dom_click_scripts_called: list[str] = []

    async def query_all(self, selector: str):
        if (
            "operate-icon-item" in selector
            or "operate-btn" in selector
            or "btn-request-resume" in selector
            or "boss-dialog" in selector
            or "exchange-tooltip" in selector
        ):
            return []
        return await super().query_all(selector)

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if script == "boss.inspect_resume_request_state":
            return {
                "hasResumeAttachment": False,
                "alreadyRequested": self.resume_confirm_clicked,
                "pendingResumeConsent": self.pending_resume_consent
                and not self.resume_consent_clicked,
                "summary": "",
            }
        if "boss_resume_consent_rect" in script:
            return {
                "found": self.pending_resume_consent and not self.resume_consent_clicked,
                "source": "boss_resume_consent_rect",
                "x": 100,
                "y": 100,
                "width": 80,
                "height": 32,
            }
        if "boss_request_resume_button_rect" in script:
            return {
                "found": True,
                "source": "boss_request_resume_button_rect",
                "x": 200,
                "y": 100,
                "width": 80,
                "height": 32,
            }
        if "boss_request_resume_confirm_rect" in script:
            return {
                "found": self.resume_button_clicked,
                "source": "boss_request_resume_confirm_rect",
                "x": 300,
                "y": 100,
                "width": 80,
                "height": 32,
            }
        if "boss_resume_consent_click" in script:
            self.dom_click_scripts_called.append("resume_consent")
            self.resume_consent_clicked = True
            return {"clicked": True, "source": "boss_resume_consent_click"}
        if "boss_request_resume_button_click" in script:
            self.dom_click_scripts_called.append("request_resume")
            self.resume_button_clicked = True
            return {"clicked": True, "source": "boss_request_resume_button_click"}
        if "boss_request_resume_confirm_click" in script:
            self.dom_click_scripts_called.append("confirm_resume")
            self.resume_confirm_clicked = True
            return {"clicked": True, "source": "boss_request_resume_confirm_click"}
        if "boss_confirm_prompt_visible" in script:
            return {"verified": self.resume_button_clicked, "source": "fake_hard_dom"}
        return await super().eval_js(script, arg)


class BossFrozenCandidatePage(BossHardResumeActionPage):
    """Fake BOSS page whose current candidate is frozen by the platform."""

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if "boss_candidate_unavailable" in script:
            return {
                "unavailable": True,
                "reason": "boss_candidate_frozen",
                "text": "该牛人已被系统冻结！牛人已被冻结，暂时无法操作",
            }
        return await super().eval_js(script, arg)


class BossFilterHierarchyPage(FakePage):
    """Real BOSS exposes the filter container before its exact option spans."""

    async def query_all(self, selector: str):
        if selector == boss_actions.selectors.MESSAGE_FILTER_OPTION:
            return [
                FakeElement(self, "filter-parent", "全部 未读\n批量"),
                FakeElement(self, "filter-unread", "未读"),
            ]
        return await super().query_all(selector)

    async def handle_element_click(self, element) -> None:
        if element.selector == "filter-unread":
            self.unread_selected = True
            return
        await super().handle_element_click(element)

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if ".chat-message-filter-left span.active" in script:
            return "未读" if self.unread_selected else "全部"
        return await super().eval_js(script, arg)


class BossUnreadHydrationPage(FakePage):
    """BOSS rows render before unread badge data finishes hydrating."""

    def __init__(self, *, eventually_ready: bool = True) -> None:
        super().__init__(
            conversations=[
                {
                    "id": "hydrated-unread",
                    "name": "延迟徽标候选人",
                    "position": "AI应用开发实习生",
                    "label": "延迟徽标候选人 AI应用开发实习生",
                    "unread_count": 2,
                }
            ],
            url=boss_actions.selectors.CHAT_URL,
        )
        self.eventually_ready = eventually_ready
        self.state_reads = 0
        self.goto_calls = 0

    async def goto(self, url: str) -> None:
        self.goto_calls += 1
        await super().goto(url)

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> bool:
        _ = selector, timeout_ms
        return True

    async def query_all(self, selector: str):
        if selector == boss_actions.selectors.MESSAGE_FILTER_OPTION:
            return [FakeElement(self, "hydration-filter-unread", "未读")]
        return await super().query_all(selector)

    async def handle_element_click(self, element) -> None:
        if element.selector == "hydration-filter-unread":
            self.unread_selected = True
            return
        await super().handle_element_click(element)

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if "boss_unread_list_state" in script:
            self.state_reads += 1
            badges_ready = self.eventually_ready and self.state_reads >= 3
            return {
                "activeFilter": "未读" if self.unread_selected else "全部",
                "rowCount": 40,
                "badgeRowCount": 35 if badges_ready else 0,
                "menuUnreadCount": 53,
                "loading": not badges_ready,
                "emptyState": False,
            }
        if ".chat-message-filter-left span.active" in script:
            return "未读" if self.unread_selected else "全部"
        return await super().eval_js(script, arg)


class BossStaleUnreadFilterPage(BossUnreadHydrationPage):
    """BOSS keeps the unread tab active while its rows still show the stale all-list."""

    def __init__(self, *, menu_unread_count: int = 27) -> None:
        super().__init__(eventually_ready=False)
        self.unread_selected = True
        self.refreshed = False
        self.menu_unread_count = menu_unread_count

    async def query_all(self, selector: str):
        if selector == boss_actions.selectors.MESSAGE_FILTER_OPTION:
            return [
                FakeElement(self, "stale-filter-all", "全部"),
                FakeElement(self, "stale-filter-unread", "未读"),
            ]
        return await super().query_all(selector)

    async def handle_element_click(self, element) -> None:
        if element.selector == "stale-filter-all":
            self.unread_selected = False
            return
        if element.selector == "stale-filter-unread":
            self.unread_selected = True
            self.refreshed = True
            return
        await super().handle_element_click(element)

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if "boss_unread_list_state" in script:
            self.state_reads += 1
            return {
                "activeFilter": "未读" if self.unread_selected else "全部",
                "rowCount": 17 if self.refreshed else 40,
                "badgeRowCount": 17 if self.refreshed else 0,
                "menuUnreadCount": self.menu_unread_count,
                "loading": False,
                "emptyState": False,
            }
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


def test_boss_send_message_preserves_low_level_failure_diagnostics(monkeypatch) -> None:
    page = FakePage(
        conversations=[
            conversation("AI产品经理", [{"sender": "other", "text": "你好"}])
        ]
    )
    page.selected_index = 0
    failure = {
        "ok": False,
        "reason": "conversation_changed_before_send",
        "expected": {"conversationId": "expected"},
        "actual": {"conversationId": "actual"},
    }

    async def fake_type_and_send(*args, **kwargs):
        _ = args, kwargs
        return failure

    monkeypatch.setattr(boss_actions, "boss_type_and_send", fake_type_and_send)

    result = asyncio.run(boss_actions.send_message(page, "你好，可以看看简历吗"))

    assert result.sent is False
    assert result.details == failure


def test_boss_operation_direct_resume_sends_prephrase_before_request() -> None:
    """运营 A/B 先发要简历话术，再执行求简历。"""

    state, page = run_case(
        Platform.BOSS,
        conversation("运营A", [{"sender": "other", "text": "你好"}]),
    )
    assert state["next_action"] == "request_resume"
    assert page.sent_messages in (
        ["你好可以看看简历吗"],
        ["你好，方便发一份简历过来吗"],
    )
    assert page.resume_requests == 1

    _, zhilian_page = run_case(
        Platform.ZHILIAN,
        conversation("运营A", [{"sender": "other", "text": "你好"}]),
    )
    assert zhilian_page.sent_messages in (
        ["你好可以看看简历吗"],
        ["你好，方便发一份简历过来吗"],
    )
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


def test_boss_ai_product_manager_direct_resume_without_screening() -> None:
    """AI 产品经理在 BOSS 走直求简历，不发筛选题。"""

    state, page = run_case(
        Platform.BOSS,
        conversation(
            "AI产品经理",
            [{"sender": "other", "text": "您好，想了解一下 AI Product Manager 岗位"}],
        ),
    )

    assert state["next_action"] == "request_resume"
    assert state["stage"] == "direct_resume"
    assert page.sent_messages in (
        ["你好，方便发一份简历过来吗"],
        ["你好，可以看看简历吗"],
    )
    assert page.resume_requests == 1


def test_senior_fullstack_platform_titles_share_resume_label() -> None:
    rules = load_chat_rules()
    titles = (
        "资深全栈工程师（AI 原生 B2B 平台 ）",
        "资深全栈工程师（AI 原生 B2B 平台 / 工程 Owner）",
        "资深全栈工程师(AI原生B2B平台/工程Owner)",
    )

    for title in titles:
        rule = select_position_rule(title, rules)
        assert rule is not None
        assert rule["directResume"] is True
        assert rule["positionRuleKey"] == "资深全栈工程师"
        assert rule["resumeJobType"] == "全栈工程师"

    assert select_position_rule("全栈工程师", rules) is None


def test_boss_senior_fullstack_question_requests_resume() -> None:
    state, page = run_case(
        Platform.BOSS,
        conversation(
            "资深全栈工程师（AI 原生 B2B 平台 ）",
            [{"sender": "other", "text": "请问这个岗位的技术栈和工作方式是什么？"}],
        ),
        rules=load_chat_rules(),
    )

    assert state["next_action"] == "request_resume"
    assert state["stage"] == "direct_resume"
    assert page.sent_messages in (
        ["你好，方便发一份简历过来吗"],
        ["你好，可以看看简历吗"],
    )
    assert page.resume_requests == 1


def test_boss_direct_resume_exchange_resume_intent_requests_resume() -> None:
    """直求简历岗位里“交换简历/发简历”是简历意图，不应当成未知岗位问题。"""

    state, page = run_case(
        Platform.BOSS,
        conversation(
            "运营A",
            [{"sender": "other", "text": "方便交换简历深度了解一下岗位吗？"}],
        ),
    )

    assert state["next_action"] == "request_resume"
    assert state["stage"] == "direct_resume"
    assert page.sent_messages in (
        ["你好可以看看简历吗"],
        ["你好，方便发一份简历过来吗"],
    )
    assert page.resume_requests == 1


def test_boss_direct_resume_job_detail_question_requests_resume() -> None:
    """直求简历岗位不答岗位细节，继续按配置求简历。"""

    state, page = run_case(
        Platform.BOSS,
        conversation(
            "外部财务产品顾问",
            [{"sender": "other", "text": "方便介绍一下岗位细节要求吗？"}],
        ),
    )

    assert state["next_action"] == "request_resume"
    assert state["stage"] == "direct_resume"
    assert page.sent_messages == ["你好，方便发一份简历过来吗"]
    assert page.resume_requests == 1


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


def test_boss_ai_solution_role_ignores_client_vendor_question_and_requests_resume() -> None:
    state, page = run_case(
        Platform.BOSS,
        conversation(
            "AI智能体解决方案负责人",
            [{"sender": "other", "text": "这个岗位是甲方还是乙方岗位？"}],
        ),
        rules=load_chat_rules(),
    )

    assert state["next_action"] == "request_resume"
    assert state["stage"] == "direct_resume"
    assert page.sent_messages in (
        ["你好，可以看看简历吗"],
        ["你好，方便发一份简历过来吗"],
    )
    assert page.resume_requests == 1


def test_ai_basic_acceptance_with_interview_question_answers_then_requests_resume() -> None:
    """AI 候选人接受基础条件后追问线上面试，先答再求简历。"""

    state, page = run_case(
        Platform.BOSS,
        conversation(
            "AI应用开发实习生",
            [
                {"sender": "me", "text": "基础条件确认话术"},
                {"sender": "other", "text": "可以接受，请问支持线上面试吗？"},
            ],
        ),
        llm=FakeLLM("accept"),
    )

    assert state["next_action"] == "request_resume"
    assert state["stage"] == "basic_accept"
    assert page.sent_messages == ["面试都是线上"]
    assert page.resume_requests == 1


def test_ai_basic_short_internship_rejects_without_reply_or_resume() -> None:
    """明确只能短期实习时，不回复、不求简历并判定不合适。"""

    rules = load_chat_rules()
    phrase = rules["positionReplies"]["AI应用开发实习生"]["initialCommonPhrase"]
    state, page = run_case(
        Platform.BOSS,
        conversation(
            "AI应用开发实习生",
            [
                {"sender": "me", "text": phrase},
                {
                    "sender": "other",
                    "text": (
                        "您好，非常感谢告知岗位福利，但我是2027届在读学生，学校还有固定课程安排，"
                        "没办法长期离岗，最多只能到岗实习2个月，无法满足公司6个月最低实习期限要求。"
                        "想跟您沟通下，是否支持短期2个月实习？"
                    ),
                },
            ],
        ),
        llm=FakeLLM("accept"),
        rules=rules,
    )

    assert state["next_action"] == "skip"
    assert state["stage"] == "candidate_policy_reject"
    assert state["decision"]["policyId"] == "ai_intern_duration_below_minimum"
    assert page.sent_messages == []
    assert page.resume_requests == 0


def test_ai_basic_job_content_question_rejects_without_reply_or_resume() -> None:
    """AI 实习生询问日常工作内容时，不回复、不求简历并判定不合适。"""

    rules = load_chat_rules()
    phrase = rules["positionReplies"]["AI应用开发实习生"]["initialCommonPhrase"]
    state, page = run_case(
        Platform.BOSS,
        conversation(
            "AI应用开发实习生",
            [
                {"sender": "me", "text": phrase},
                {
                    "sender": "other",
                    "text": (
                        "您好，感谢您的介绍。工作地点和至少6个月的实习时间我都可以接受。"
                        "想再了解一下，这个岗位日常主要负责哪些工作内容呢？"
                    ),
                },
            ],
        ),
        llm=FakeLLM("accept"),
        rules=rules,
    )

    assert state["next_action"] == "skip"
    assert state["stage"] == "candidate_policy_reject"
    assert state["decision"]["policyId"] == "ai_intern_job_content_question"
    assert page.sent_messages == []
    assert page.resume_requests == 0


def test_loaded_rules_use_qualified_online_interview_answer() -> None:
    answer = find_knowledge_answer(
        "可以线上面试吗",
        load_chat_rules(),
        position="AI应用开发实习生",
    )

    assert answer == "面试基本都是线上，公司膨润土应用技术和销售岗位终面需要到面"


def test_ai_basic_acceptance_with_resume_offer_question_requests_resume() -> None:
    rules = load_chat_rules()
    phrase = rules["positionReplies"]["AI应用开发实习生"]["initialCommonPhrase"]
    state, page = run_case(
        Platform.BOSS,
        conversation(
            "AI应用开发实习生",
            [
                {"sender": "me", "text": phrase},
                {"sender": "other", "text": "能接受"},
                {"sender": "other", "text": "简历能发您一份，方便查阅吗😊"},
            ],
        ),
        rules=rules,
    )

    assert state["next_action"] == "request_resume"
    assert state["stage"] == "basic_accept"
    assert page.resume_requests == 1


def test_ai_basic_leading_acknowledgement_accepts_without_swallowing_hesitation() -> None:
    accepted = asyncio.run(judge_candidate_reply("好的，我是已经毕业的应届生"))
    hesitant = asyncio.run(judge_candidate_reply("好的，我再考虑一下"))

    assert accepted.status == "accept"
    assert hesitant.status == "unclear"


def test_hrbp_unanswered_detail_question_skips_answer_and_starts_screening() -> None:
    """HRBP 细节问题无法回答时不回复问题，直接进入筛选。"""

    state, page = run_case(
        Platform.BOSS,
        conversation(
            "HRBP",
            [{"sender": "other", "text": "您好，hrbp职位还在招吗，方便介绍岗位细节吗？"}],
        ),
    )

    assert state["next_action"] == "ask_screening"
    assert state["stage"] == "screening_question_sent"
    assert page.sent_messages == ["你好，我们这边在湖州长兴这边，然后还是单休，可以接受吗"]
    assert page.resume_requests == 0


def test_sales_paid_training_question_uses_question_patterns_without_requesting_resume() -> None:
    """筛选岗位能答的问题先答，再继续发送岗位筛选问题。"""

    state, page = run_case(
        Platform.BOSS,
        conversation(
            "销售管培生",
            [{"sender": "other", "text": "请问是带薪培训吗，如果是的话我接受"}],
        ),
    )

    assert state["next_action"] == "ask_screening"
    assert page.sent_messages == ["是带薪培训", "你是否接受出差？"]
    assert page.resume_requests == 0


def test_screening_unknown_question_skips_answer_and_asks_next_question() -> None:
    """筛选岗位遇到不能回答的问句时不回复问题，继续下一筛选动作。"""

    state, page = run_case(
        Platform.BOSS,
        conversation(
            "国际业务管培生",
            [{"sender": "other", "text": "希望和你聊聊这个职位，是否有时间呢？"}],
        ),
    )

    assert state["next_action"] == "ask_screening"
    assert state["stage"] == "screening_question_sent"
    assert len(page.sent_messages) == 1


def test_boss_rhetorical_hr_attack_is_not_a_business_question() -> None:
    assert looks_like_question("真不敢想你这个人事是怎么当上的") is False
    assert looks_like_question("这个岗位怎么安排面试") is True


def test_specific_question_pattern_wins_over_position_boost() -> None:
    """组合问法比岗位分区里的泛薪资关键词更具体，应优先命中。"""

    rules = sample_rules()
    rules["companyKnowledgeBase"]["sections"] = {
        "人力资源": {
            "matchPositions": ["人力资源管培生"],
            "faq": [
                {
                    "topic": "hrSalary",
                    "questionPatterns": ["薪资"],
                    "answer": "具体工资由老板根据面试和个人情况定",
                }
            ],
        }
    }
    rules["companyKnowledgeBase"]["faq"].append(
        {
            "topic": "scheduleAndTrainingCompensation",
            "questionPatterns": ["工作时间和薪资构成"],
            "answer": "工作时间是8-11，13-17，培训期间一天150",
        }
    )

    answer = find_knowledge_answer(
        "每天的工作时间和薪资构成是怎么样的呀",
        rules,
        position="人力资源管培生",
    )

    assert answer == "工作时间是8-11，13-17，培训期间一天150"


def test_boss_ai_intern_compound_food_lodging_and_payday_question_returns_all_topics() -> None:
    answers = find_knowledge_answers(
        "食宿自理吗，工资是一个月一结吗？",
        load_chat_rules(),
        position="AI应用开发实习生",
    )

    assert [item["topic"] for item in answers] == [
        "accommodation",
        "mealsAndBenefits",
        "salaryPaymentDate",
    ]
    assert [item["answer"] for item in answers] == [
        "公司包住，两人间",
        "食堂3元一顿",
        "每月10号发工资",
    ]


def test_boss_ai_intern_keeps_salary_amount_when_amount_and_payday_are_both_explicit() -> None:
    answers = find_knowledge_answers(
        "实习薪资多少，什么时候发工资？",
        load_chat_rules(),
        position="AI应用开发实习生",
    )

    assert [item["topic"] for item in answers] == ["salaryAmount", "salaryPaymentDate"]
    assert [item["answer"] for item in answers] == ["实习是150一天", "每月10号发工资"]


def test_boss_ai_intern_answers_all_candidate_messages_since_last_recruiter_reply() -> None:
    rules = load_chat_rules()
    phrase = rules["positionReplies"]["AI应用开发实习生"]["initialCommonPhrase"]
    state, page = run_case(
        Platform.BOSS,
        conversation(
            "AI应用开发实习生",
            [
                {"sender": "me", "text": phrase},
                {"sender": "other", "text": "可以的"},
                {"sender": "other", "text": "咱们的工作时间是？"},
                {"sender": "other", "text": "还在吗 姐姐"},
            ],
        ),
        rules=rules,
    )

    assert page.sent_messages == ["在的，岗位还在招聘；8-11点，13-17点"]
    assert page.resume_requests == 1
    assert state["next_action"] == "request_resume"
    assert state["stage"] == "basic_accept"


def test_boss_ai_intern_combines_location_and_accommodation_in_one_reply() -> None:
    rules = load_chat_rules()
    phrase = rules["positionReplies"]["AI应用开发实习生"]["initialCommonPhrase"]
    state, page = run_case(
        Platform.BOSS,
        conversation(
            "AI应用开发实习生",
            [
                {"sender": "me", "text": phrase},
                {"sender": "other", "text": "您好，工作地点在哪，提供住宿吗"},
            ],
        ),
        rules=rules,
    )

    assert page.sent_messages == ["在湖州长兴泗安镇；公司包住，两人间"]
    assert state["next_action"] == "answer_question"
    assert state["stage"] == "knowledge_hit"


def test_boss_ai_intern_housing_self_resolved_question_matches_accommodation() -> None:
    answers = find_knowledge_answers(
        "住房是自行解决吗",
        load_chat_rules(),
        position="AI应用开发实习生",
    )

    assert [item["topic"] for item in answers] == ["accommodation"]
    assert [item["answer"] for item in answers] == ["公司包住，两人间"]


def test_boss_ai_intern_what_business_question_matches_company_business() -> None:
    answers = find_knowledge_answers(
        "做什么业务的",
        load_chat_rules(),
        position="AI应用开发实习生",
    )

    assert [item["topic"] for item in answers] == ["companyBusiness"]
    assert [item["answer"] for item in answers] == ["主要做膨润土"]


def test_hr_screening_answer_with_faq_replies_before_next_question() -> None:
    rules = load_chat_rules()
    state, page = run_case(
        Platform.BOSS,
        conversation(
            "人力资源管培生",
            [
                {
                    "sender": "me",
                    "text": "你好，我们这边在湖州长兴这边，然后还是单休，可以接受吗",
                },
                {
                    "sender": "other",
                    "text": "可以的，提供住宿吗？薪资构成怎么样呢？",
                },
            ],
        ),
        rules=rules,
    )

    assert page.sent_messages[0] == "工作时间是8-11，13-17，培训期间一天150；公司包住，两人间"
    assert page.sent_messages[1] in {
        "你好，这个岗位需要出差，可以接受吗",
        "你好，你可以接受出差吗",
    }
    assert state["next_action"] == "ask_screening"
    assert state["stage"] == "screening_question_sent"


def test_known_question_reply_preserves_negative_screening_decision() -> None:
    rules = load_chat_rules()
    state, page = run_case(
        Platform.BOSS,
        conversation(
            "人力资源管培生",
            [
                {"sender": "me", "text": "你好，这个岗位需要出差，可以接受吗"},
                {"sender": "other", "text": "不能接受出差，请问提供住宿吗？"},
            ],
        ),
        rules=rules,
    )

    assert page.sent_messages == ["公司包住，两人间"]
    assert state["next_action"] == "skip"
    assert state["stage"] == "screening_reject"
    assert page.resume_requests == 0


def test_boss_ai_intern_answers_known_question_before_initial_phrase() -> None:
    """首次提问也必须先答候选人，再发送基础条件。"""

    rules = load_chat_rules()
    phrase = rules["positionReplies"]["AI应用开发实习生"]["initialCommonPhrase"]

    state, page = run_case(
        Platform.BOSS,
        conversation(
            "AI应用开发实习生",
            [{"sender": "other", "text": "请问每天的工作时间是几点？"}],
        ),
        rules=rules,
    )

    assert state["next_action"] == "ask_basic_conditions"
    assert state["stage"] == "basic_phrase_sent"
    assert page.sent_messages == ["8-11点，13-17点", phrase]


def test_boss_ai_intern_answers_standard_clock_in_time_after_basic_accept() -> None:
    rules = load_chat_rules()
    phrase = rules["positionReplies"]["AI应用开发实习生"]["initialCommonPhrase"]
    state, page = run_case(
        Platform.BOSS,
        conversation(
            "AI应用开发实习生",
            [
                {"sender": "me", "text": phrase},
                {
                    "sender": "other",
                    "text": "都能接受，可以问一下公司上下班标准打卡时间是几点？",
                },
            ],
        ),
        rules=rules,
    )

    assert page.sent_messages == ["8-11点，13-17点"]
    assert page.resume_requests == 1
    assert state["next_action"] == "request_resume"
    assert state["stage"] == "basic_accept"


def test_any_required_screening_accepts_explicit_alternative_experience() -> None:
    screening = {
        "mode": "ask_any_required_question",
        "questions": [
            {"text": "你好，你之前有了解过膨润土吗", "required": True},
            {"text": "你好，你熟悉涂料原料吗", "required": True},
        ],
    }

    analysis = asyncio.run(
        analyze_position_screening(
            [
                {"sender": "me", "text": "你好，你之前有了解过膨润土吗"},
                {
                    "sender": "other",
                    "text": "没有膨润土经验，但做了十五年涂料销售",
                },
            ],
            screening,
        )
    )

    assert analysis["status"] == "accept"
    assert analysis["reason"] == "any_required_question_accept"


def test_screening_does_not_apply_unrelated_positive_experience_to_certificate() -> None:
    screening = {
        "mode": "ask_any_required_question",
        "questions": [
            {"text": "你好，你有弱电电工证吗", "required": True},
            {"text": "你好，你熟悉 PLC 吗", "required": True},
        ],
    }

    analysis = asyncio.run(
        analyze_position_screening(
            [
                {"sender": "me", "text": "你好，你有弱电电工证吗"},
                {
                    "sender": "other",
                    "text": "没有弱电电工证，但做了十五年涂料销售",
                },
            ],
            screening,
        )
    )

    assert analysis["status"] == "not_asked"
    assert analysis["nextQuestion"]["text"] == "你好，你熟悉 PLC 吗"


def test_coating_sales_does_not_replace_industrial_coating_formula_experience() -> None:
    screening = {
        "mode": "ask_required_questions",
        "questions": [
            {"text": "你好，你熟悉工业涂料配方吗", "required": True},
        ],
    }

    analysis = asyncio.run(
        analyze_position_screening(
            [
                {"sender": "me", "text": "你好，你熟悉工业涂料配方吗"},
                {
                    "sender": "other",
                    "text": "没有做过工业涂料配方，但做了十五年涂料销售",
                },
            ],
            screening,
        )
    )

    assert analysis["status"] == "reject"


def test_no_problem_is_an_acceptance_not_a_generic_negation() -> None:
    result = asyncio.run(judge_candidate_reply("没有问题，可以接受"))

    assert result.status == "accept"


def test_closing_phrase_without_pending_question_sends_nothing() -> None:
    state, page = run_case(
        Platform.BOSS,
        conversation(
            "AI应用开发实习生",
            [{"sender": "other", "text": "打扰了，谢谢"}],
        ),
        rules=load_chat_rules(),
    )

    assert state["next_action"] == "wait"
    assert state["stage"] == "candidate_closing"
    assert page.sent_messages == []
    assert page.resume_requests == 0


def test_good_ack_after_screening_question_is_not_treated_as_closing() -> None:
    state, page = run_case(
        Platform.BOSS,
        conversation(
            "销售管培生",
            [
                {"sender": "me", "text": "你是否接受出差？"},
                {"sender": "other", "text": "好的"},
            ],
        ),
    )

    assert state["next_action"] == "request_resume"
    assert page.resume_requests == 1


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


def test_boss_unread_filter_stops_on_platform_security_warning() -> None:
    class SecurityWarningPage:
        async def eval_js(self, script: str, arg: object | None = None) -> dict[str, object]:
            _ = script, arg
            return {
                "blocked": True,
                "title": "风险提示",
                "text": "不得使用任何第三方插件、外挂、软件等招聘辅助工具",
            }

    result = asyncio.run(boss_actions.select_unread_filter(SecurityWarningPage()))  # type: ignore[arg-type]

    assert result["selected"] is False
    assert result["ready"] is False
    assert result["status"] == "security_warning"
    assert result["reason"] == "boss_security_warning"


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


def test_boss_request_resume_uses_mouse_for_button_and_confirm(monkeypatch) -> None:
    """DOM 只定位求简历按钮，按钮和确认必须由模拟鼠标点击。"""

    page = BossHardResumeActionPage()

    async def fake_mouse_click(target_page, rect, **kwargs):
        _ = kwargs
        if rect.get("source") == "boss_request_resume_button_rect":
            target_page.resume_button_clicked = True
        if rect.get("source") == "boss_request_resume_confirm_rect":
            target_page.resume_confirm_clicked = True
        return {"ok": True, "method": "humanized_mouse"}

    monkeypatch.setattr(boss_actions.actions_resume, "boss_click_rect", fake_mouse_click)

    result = asyncio.run(boss_actions.request_resume(page))

    assert result["requested"] is True
    assert result["confirmed"] is True
    assert page.resume_button_clicked is True
    assert page.resume_confirm_clicked is True
    assert page.dom_click_scripts_called == []


def test_boss_request_resume_skips_frozen_candidate_without_clicking(monkeypatch) -> None:
    page = BossFrozenCandidatePage()
    click_attempts: list[dict[str, object]] = []

    async def fake_mouse_click(target_page, rect, **kwargs):
        _ = target_page, kwargs
        click_attempts.append(rect)
        return {"ok": False, "reason": "unexpected_click"}

    monkeypatch.setattr(boss_actions.actions_resume, "boss_click_rect", fake_mouse_click)

    result = asyncio.run(boss_actions.request_resume(page))

    assert result["ok"] is True
    assert result["candidateUnavailable"] is True
    assert result["outcome"] == "candidate_frozen"
    assert result["reason"] == "boss_candidate_frozen"
    assert click_attempts == []


def test_boss_request_resume_ignores_pending_consent_and_only_requests_resume(
    monkeypatch,
) -> None:
    """候选人主动发附件时也不得点同意，只走求简历动作。"""

    page = BossHardResumeActionPage(pending_resume_consent=True)

    async def fake_mouse_click(target_page, rect, **kwargs):
        _ = kwargs
        source = rect.get("source")
        if source == "boss_request_resume_button_rect":
            target_page.resume_button_clicked = True
        elif source == "boss_request_resume_confirm_rect":
            target_page.resume_confirm_clicked = True
        elif source == "boss_resume_consent_rect":
            raise AssertionError("BOSS pending consent must not be clicked")
        return {"ok": True, "method": "humanized_mouse"}

    monkeypatch.setattr(boss_actions.actions_resume, "boss_click_rect", fake_mouse_click)

    result = asyncio.run(boss_actions.request_resume(page))

    assert result["requested"] is True
    assert result["confirmed"] is True
    assert page.resume_consent_clicked is False
    assert page.resume_button_clicked is True
    assert page.resume_confirm_clicked is True
    assert page.dom_click_scripts_called == []


def test_boss_resume_state_requires_actionable_consent_button() -> None:
    script = boss_dom_scripts.INSPECT_RESUME_REQUEST_STATE_JS

    assert "consentActionable" in script
    assert 'classList.contains("disabled")' in script
    assert 'pointerEvents !== "none"' in script
    assert "pendingResumeConsent: Boolean(consentPrompt && consentActionable)" in script


def test_boss_request_resume_confirms_request_when_consent_card_appears(
    monkeypatch,
) -> None:
    """待同意附件卡片出现时仍只完成求简历确认，不点击同意。"""

    page = BossHardResumeActionPage()

    async def fake_mouse_click(target_page, rect, **kwargs):
        _ = kwargs
        source = rect.get("source")
        if source == "boss_request_resume_button_rect":
            target_page.resume_button_clicked = True
            target_page.pending_resume_consent = True
        elif source == "boss_resume_consent_rect":
            raise AssertionError("BOSS pending consent must not be clicked")
        elif source == "boss_request_resume_confirm_rect":
            target_page.resume_confirm_clicked = True
        return {"ok": True, "method": "humanized_mouse"}

    monkeypatch.setattr(boss_actions.actions_resume, "boss_click_rect", fake_mouse_click)

    result = asyncio.run(boss_actions.request_resume(page))

    assert result["ok"] is True
    assert result["outcome"] == "request_confirmed"
    assert page.resume_consent_clicked is False
    assert page.resume_confirm_clicked is True


def test_boss_request_resume_reports_dialog_replacement_without_terminal_state(
    monkeypatch,
) -> None:
    page = BossHardResumeActionPage()
    page.resume_button_clicked = True

    async def state_changed_click(target_page):
        _ = target_page
        return {
            "ok": False,
            "reason": "resume_request_state_changed",
            "guard": {"reason": "resume_request_state_changed"},
        }

    monkeypatch.setattr(
        boss_actions.actions_resume,
        "_click_request_resume_confirm",
        state_changed_click,
    )

    result = asyncio.run(boss_actions.request_resume(page))

    assert result["ok"] is False
    assert result["outcome"] == "resume_request_state_changed"
    assert result["reason"] == "resume_request_state_changed"
    assert result["beforeState"]["alreadyRequested"] is False
    assert result["afterState"]["alreadyRequested"] is False


def test_boss_runner_marks_unhandled_resume_request_as_failure() -> None:
    page = FakePage(
        conversations=[
            conversation("DirectRole", [{"sender": "other", "text": "你好"}])
        ]
    )
    adapter = BossAdapter(page, owner="宋峰峰", dry_run=False)

    async def fail_request_resume() -> dict[str, object]:
        return {
            "ok": True,
            "requested": False,
            "confirmed": False,
            "reason": "resume_request_confirm_failed",
        }

    adapter.request_resume = fail_request_resume  # type: ignore[method-assign]
    runner = ConversationRunner(adapter, rules=sample_rules())

    state = asyncio.run(runner.run_current())

    assert state["next_action"] == "request_resume_failed"
    assert state["stage"] == "request_resume_action_failed"
    assert state["decision"]["result"]["reason"] == "resume_request_confirm_failed"


def test_boss_runner_treats_frozen_candidate_as_safe_terminal_skip() -> None:
    page = FakePage(
        conversations=[
            conversation("DirectRole", [{"sender": "other", "text": "你好"}])
        ]
    )
    adapter = BossAdapter(page, owner="宋峰峰", dry_run=False)

    async def frozen_request_resume() -> dict[str, object]:
        return {
            "ok": True,
            "outcome": "candidate_frozen",
            "requested": False,
            "candidateUnavailable": True,
            "skipped": True,
            "reason": "boss_candidate_frozen",
        }

    adapter.request_resume = frozen_request_resume  # type: ignore[method-assign]
    runner = ConversationRunner(adapter, rules=sample_rules())

    state = asyncio.run(runner.run_current())

    assert state["next_action"] == "wait"
    assert state["stage"] == "candidate_unavailable"
    assert state["decision"]["result"]["reason"] == "boss_candidate_frozen"


def test_boss_skill_documents_request_resume_function_call_contract() -> None:
    """BOSS skill 必须写清楚求简历只能调用 recruiter_request_resume。"""

    root = Path(__file__).resolve().parents[2]
    skill = root / "app" / "agent" / "skills" / "boss-recruiter-automation" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")

    for expected in (
        "求简历、同意候选人主动发来的附件简历，都必须调用 `recruiter_request_resume`",
        "boss_resume_consent_click",
        "boss_request_resume_button_click",
        "boss_confirm_prompt_visible",
        "boss_request_resume_confirm_click",
        "不要让模型/agent 临场猜 selector 或手工点按钮",
    ):
        assert expected in text


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


def test_boss_open_chat_page_waits_for_chat_filter_before_unread_scan() -> None:
    """BOSS SPA 刚 goto 后要等聊天筛选栏渲染，否则会误判没有未读。"""

    page = DelayedBossChatPage()

    asyncio.run(boss_actions.open_chat_page(page))
    result = asyncio.run(boss_actions.select_unread_filter(page))
    refs = asyncio.run(boss_actions.read_unread_conversations(page, owner="宋峰峰"))

    assert result["selected"] is True
    assert [item.conversation_id for item in refs] == ["delayed-unread"]
    assert page.waited_selectors


def test_boss_unread_filter_clicks_exact_option_not_parent_container() -> None:
    page = BossFilterHierarchyPage()

    result = asyncio.run(boss_actions.select_unread_filter(page))

    assert result["selected"] is True
    assert "filter-unread" in page.clicks
    assert "filter-parent" not in page.clicks


def test_boss_open_chat_page_reuses_ready_page_without_reload() -> None:
    page = BossUnreadHydrationPage()

    asyncio.run(boss_actions.open_chat_page(page))

    assert page.goto_calls == 0


def test_boss_unread_filter_waits_until_delayed_badges_are_ready(monkeypatch) -> None:
    page = BossUnreadHydrationPage()
    monkeypatch.setattr(boss_actions, "BOSS_UNREAD_READY_POLL_MS", 0)

    result = asyncio.run(boss_actions.select_unread_filter(page))

    assert result["selected"] is True
    assert result["ready"] is True
    assert result["status"] == "ready_with_unread"
    assert page.state_reads >= 3


def test_boss_unread_filter_reuses_already_active_state(monkeypatch) -> None:
    page = BossUnreadHydrationPage()
    page.unread_selected = True
    monkeypatch.setattr(boss_actions, "BOSS_UNREAD_READY_POLL_MS", 0)

    result = asyncio.run(boss_actions.select_unread_filter(page))

    assert result["selected"] is True
    assert result["ready"] is True
    assert result["click"]["method"] == "already_active"
    assert page.clicks == []


def test_boss_unread_state_with_menu_count_does_not_false_drain(monkeypatch) -> None:
    page = BossUnreadHydrationPage(eventually_ready=False)
    page.unread_selected = True
    monkeypatch.setattr(boss_actions, "BOSS_UNREAD_READY_POLL_MS", 0)

    result = asyncio.run(
        boss_actions.wait_for_unread_list_ready(page, timeout_ms=1)
    )

    assert result["ready"] is False
    assert result["reason"] == "boss_unread_list_not_ready"
    assert result["state"]["menuUnreadCount"] == 53


def test_boss_unread_state_detects_stale_active_filter_without_waiting_full_timeout(
    monkeypatch,
) -> None:
    page = BossStaleUnreadFilterPage()
    monkeypatch.setattr(boss_actions, "BOSS_UNREAD_READY_POLL_MS", 0)

    result = asyncio.run(
        boss_actions.wait_for_unread_list_ready(page, timeout_ms=100)
    )

    assert result["ready"] is False
    assert result["status"] == "stale_active_filter"
    assert result["reason"] == "boss_unread_filter_stale"
    assert page.state_reads >= 2


def test_boss_unread_filter_refreshes_stale_active_list(monkeypatch) -> None:
    page = BossStaleUnreadFilterPage()
    readiness = iter(
        (
            {
                "ready": False,
                "status": "stale_active_filter",
                "reason": "boss_unread_filter_stale",
                "state": {"menuUnreadCount": 27},
            },
            {
                "ready": True,
                "status": "ready_with_unread",
                "reason": "",
                "state": {"badgeRowCount": 17},
            },
        )
    )

    async def fake_wait(target_page, **kwargs):
        _ = target_page, kwargs
        return next(readiness)

    async def fake_click(target_page, element, **kwargs):
        _ = kwargs
        await target_page.handle_element_click(element)
        return {"ok": True, "method": "humanized_mouse"}

    monkeypatch.setattr(boss_actions, "wait_for_unread_list_ready", fake_wait)
    monkeypatch.setattr(boss_actions, "boss_click_element", fake_click)

    result = asyncio.run(boss_actions.select_unread_filter(page))

    assert result["ready"] is True
    assert result["status"] == "ready_with_unread"
    assert result["refreshed"] is True
    assert page.refreshed is True


def test_boss_unread_state_detects_stale_rows_after_menu_count_reaches_zero(
    monkeypatch,
) -> None:
    page = BossStaleUnreadFilterPage(menu_unread_count=0)
    monkeypatch.setattr(boss_actions, "BOSS_UNREAD_READY_POLL_MS", 0)

    result = asyncio.run(
        boss_actions.wait_for_unread_list_ready(page, timeout_ms=100)
    )

    assert result["ready"] is False
    assert result["status"] == "stale_active_filter"
    assert result["reason"] == "boss_unread_filter_stale"


def test_boss_send_message_uses_atomic_humanized_type_and_send(monkeypatch) -> None:
    """BOSS 发送必须委托给不可拆分的逐字输入与鼠标发送序列。"""

    page = FakePage(
        conversations=[
            {
                "id": "humanized-send",
                "name": "测试候选人",
                "position": "AI产品经理",
                "label": "测试候选人 AI产品经理",
                "messages": [{"sender": "other", "text": "你好"}],
            }
        ]
    )
    calls: list[str] = []

    async def fake_type_and_send(
        target_page,
        text: str,
        *,
        verify_sent,
        profile=None,
        expected_conversation=None,
    ) -> dict[str, object]:
        _ = profile, expected_conversation
        calls.append(text)
        target_page.append_sent_message(text)
        verified = await verify_sent()
        return {"ok": bool(verified.get("verified")), "verified": True}

    monkeypatch.setattr(boss_actions, "boss_type_and_send", fake_type_and_send)

    result = asyncio.run(boss_actions.send_message(page, "逐字输入后发送"))

    assert result.sent is True
    assert calls == ["逐字输入后发送"]


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


def test_screening_rejects_negated_accept_phrases() -> None:
    """“接受”出现在否定短语中时不得被关键词兜底误判为通过。"""

    screening = {
        "mode": "ask_required_questions",
        "questions": [
            {
                "id": "single_rest",
                "text": "你好，我们这边在湖州长兴，还是单休，你可以接受吗",
                "required": True,
            }
        ],
    }
    question = screening["questions"][0]["text"]

    for answer in ("不好意思哈！单休接受不了", "我不能接受单休", "不太能接受"):
        fallback = asyncio.run(judge_candidate_reply(answer))
        analysis = asyncio.run(
            analyze_position_screening(
                [
                    {"sender": "me", "text": question},
                    {"sender": "other", "text": answer},
                ],
                screening,
            )
        )

        assert fallback.status == "reject", answer
        assert analysis["status"] == "reject", answer


def test_screening_does_not_reject_salary_or_job_content_questions() -> None:
    screening = {
        "mode": "ask_required_questions",
        "questions": [
            {
                "id": "single_rest",
                "text": "你好，我们这边在湖州长兴，还是单休，你可以接受吗",
                "required": True,
            }
        ],
    }
    question = screening["questions"][0]["text"]
    answer = "请问无责底薪是多少呢？ 请问具体工作内容是哪些呢？\n合适"

    fallback = asyncio.run(judge_candidate_reply(answer))
    analysis = asyncio.run(
        analyze_position_screening(
            [
                {"sender": "me", "text": question},
                {"sender": "other", "text": "请问无责底薪是多少呢？"},
                {"sender": "other", "text": "请问具体工作内容是哪些呢？\n合适"},
            ],
            screening,
        )
    )

    assert fallback.status == "unclear"
    assert analysis["status"] == "unclear"


def test_screening_still_rejects_missing_required_experience() -> None:
    screening = {
        "mode": "ask_required_questions",
        "questions": [
            {
                "id": "sales_experience",
                "text": "你之前做过化工原料外贸销售吗",
                "required": True,
            }
        ],
    }

    analysis = asyncio.run(
        analyze_position_screening(
            [
                {"sender": "me", "text": screening["questions"][0]["text"]},
                {"sender": "other", "text": "没有"},
            ],
            screening,
        )
    )

    assert analysis["status"] == "reject"


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
    *,
    rules: dict[str, object] | None = None,
):
    """按平台运行单条会话。"""

    page = FakePage(conversations=[convo])
    adapter = (
        BossAdapter(page, owner="和新红")
        if platform == Platform.BOSS
        else ZhilianAdapter(page, owner="宋峰峰")
    )
    sink = InMemoryDecisionSink()
    runner = ConversationRunner(
        adapter,
        rules=rules or sample_rules(),
        llm=llm,
        decision_sink=sink,
    )
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
                "screening": {
                    "mode": "ask_required_questions",
                    "questions": [
                        {"text": "你是否接受出差？", "required": True},
                    ],
                },
            },
            "HRBP": {
                "category": "HRBP",
                "screeningFirstQuestionPatterns": [
                    "还在招",
                    "岗位细节",
                    "细节要求",
                ],
                "screening": {
                    "mode": "ask_required_questions",
                    "questions": [
                        {
                            "text": "你好，我们这边在湖州长兴这边，然后还是单休，可以接受吗",
                            "required": True,
                        },
                    ],
                },
            },
            "国际业务管培生": {
                "category": "foreign_trade",
                "screening": {
                    "mode": "ask_required_questions",
                    "questions": [
                        {
                            "text": "你好，方便问下你之前做过化工原料外贸销售吗",
                            "required": True,
                        },
                    ],
                },
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
            "AI产品经理": {
                "category": "ai_product_manager_direct_resume",
                "directResume": True,
                "resumeJobType": "AI产品经理",
                "resumeRequestPrompt": "你好，方便发一份简历过来吗",
                "resumeRequestPrompts": [
                    "你好，方便发一份简历过来吗",
                    "你好，可以看看简历吗",
                ],
                "aliases": ["AI 产品经理", "AI Product Manager", "AI PM"],
                "screeningQuestions": [],
            },
            "DirectRole": {
                "category": "direct",
                "directResume": True,
                "resumeJobType": "DirectRole",
                "resumeRequestPrompt": "please send resume",
            },
        },
        "companyKnowledgeBase": {
            "faq": [
                {
                    "topic": "hiringStatus",
                    "questionPatterns": ["还在招", "还招"],
                    "answer": "还在招的",
                },
                {
                    "topic": "salesCompensation",
                    "questionPatterns": ["带薪培训"],
                    "answer": "是带薪培训",
                },
                {
                    "topic": "interviewProcess",
                    "questionPatterns": ["线上面试", "线下面试"],
                    "answer": "面试都是线上",
                },
            ]
        },
    }
