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
    _normalize_unread_rows,
    click_thread_by_state,
    find_next_thread,
    read_chat_context,
    read_unread_conversations,
    select_positions,
    select_unread_filter,
    should_skip_thread_label,
    verify_opened_candidate,
)
from app.platforms.job51.actions_chat import (
    open_chat_page as open_job51_chat_page,
)
from app.platforms.job51.actions_navigation import _wait_chat_shell, open_chat_page
from app.platforms.job51.actions_resume import (
    InMemoryResumeDownloadMemory,
    _open_attachment_resume_preview,
    resume_download_suitability_guard,
    save_resume_bytes,
    validate_resume_bytes,
)
from app.platforms.job51.actions_resume_close import cleanup_resume_overlays
from app.platforms.job51.adapter import Job51Adapter
from app.platforms.job51.dom_scripts import READ_CHAT_CONTEXT_JS
from app.platforms.types import MessageSender
from scripts.platform_once_common import (
    _find_candidate_row,
    _process,
    _seen_keys_for_processed_item,
)


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


def test_job51_unread_filter_active_state_is_verified() -> None:
    """51job 未读筛选复用可靠动作层，并校验 active 状态。"""

    page = FakePage(
        conversations=[conversation("销售管培生", [{"sender": "other", "text": "你好"}])]
    )
    result = asyncio.run(select_unread_filter(page))
    assert result["selected"] is True
    assert page.unread_selected is True
    assert result["refreshed"] is False


def test_job51_unread_filter_refreshes_when_already_checked() -> None:
    """51job 未读已勾选时，先取消再勾选，刷新未读列表。"""

    page = FakePage(
        conversations=[conversation("销售管培生", [{"sender": "other", "text": "你好"}])],
        unread_selected=True,
    )
    result = asyncio.run(select_unread_filter(page))
    assert result["selected"] is True
    assert result["refreshed"] is True
    assert [item["step"] for item in result["actions"]] == [
        "uncheck_for_refresh",
        "check_unread",
    ]


def test_job51_chat_shell_accepts_logged_in_chat_text() -> None:
    """51job 聊天页 CSS 短暂不可见时，用页面特征避免无意义重跳转。"""

    page = FakePage(
        url="https://ehire.51job.com/Revision/chat?rt=1",
        body_text="人才沟通 全部职位 未读 AI沟通",
    )

    assert asyncio.run(_wait_chat_shell(page, timeout_ms=100)) is True


def test_job51_open_chat_page_never_clicks_app_entry_when_chat_shell_is_slow() -> None:
    """51job 聊天页慢加载时只直达 ehire 聊天页，不点 app.51job 入口。"""

    page = SlowJob51ChatPage()

    asyncio.run(open_chat_page(page))

    assert page.clicks == []
    assert page.gotos == ["https://ehire.51job.com/Revision/chat"]
    assert page.url == "https://ehire.51job.com/Revision/chat"


def test_job51_open_chat_page_installs_app_blocker_before_filter_click() -> None:
    """51job preflight clicks must be guarded before any position/unread action."""

    page = GuardedPreflightClickPage(
        conversations=[conversation("AI应用开发实习生", [{"sender": "other", "text": "你好"}])]
    )

    asyncio.run(open_job51_chat_page(page))
    asyncio.run(select_positions(page))

    assert page.app_download_blocker_installed is True
    assert page.context_popup_blocker_installed is True
    assert page.app_download_popups == 0


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


def test_job51_verify_opened_candidate_uses_dom_context_fallback_until_stable() -> None:
    """Live CDP pages may only expose the generic DOM context script after row click."""

    page = DelayedJob51ContextPage(
        [
            {},
            {"name": "Alice", "position": "AI Intern", "label": "Alice AI Intern\nhello"},
        ]
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {"label": "1\nAlice AI Intern\n9:32\nhello", "name": "Alice", "position": "AI Intern"},
            chat_ready=True,
            timeout_ms=50,
            interval_ms=0,
        )
    )

    assert opened["opened"] is True
    assert page.dom_context_reads == 2


def test_job51_read_chat_context_parses_batch_panel_candidate_message() -> None:
    """51job batch chat panels expose messages outside div.im-message-item."""

    page = BatchPanelDomContextPage()

    context = asyncio.run(read_chat_context(page, owner="宋峰峰"))

    assert page.extension_reads == 1
    assert page.dom_reads == 1
    assert context.candidate.name == "郭超"
    assert context.candidate.applied_position == "膨润土销售人员"
    assert context.messages[-1].sender == MessageSender.CANDIDATE
    assert context.messages[-1].text == "你好，简历已投递，期待回复~"
    assert context.should_reply is True


def test_job51_click_thread_by_state_falls_back_to_row_index() -> None:
    """51job 行点击支持 row state fallback，避开真实虚拟列表原生点击不稳。"""

    page = FakePage(
        conversations=[
            conversation(
                "销售管培生",
                [{"sender": "other", "text": "你好"}],
                label="候选人A",
            ),
            conversation(
                "AI应用开发实习生",
                [{"sender": "other", "text": "你好"}],
                label="候选人B",
            ),
        ]
    )

    result = asyncio.run(click_thread_by_state(page, {"index": 1, "label": "候选人B"}))

    assert result["clicked"] is True
    assert page.selected_index == 1


def test_job51_unread_row_state_preserves_candidate_identity_fields() -> None:
    """Live 51job rows need name and position for post-click identity verification."""

    rows = _normalize_unread_rows(
        [
            {
                "index": 0,
                "id": "",
                "label": "3\nAlice AI Intern\n9:32\nhello",
                "name": "Alice",
                "position": "AI Intern",
                "unreadCount": 3,
            }
        ]
    )

    assert rows == [
        {
            "index": 0,
            "id": "",
            "label": "3\nAlice AI Intern\n9:32\nhello",
            "name": "Alice",
            "position": "AI Intern",
            "unread_count": 3,
        }
    ]


def test_job51_operation_and_finance_have_prompt() -> None:
    """运营 A/B 和财务 AI 直求简历岗位都会先发要简历话术。"""

    _, page = run_case(conversation("运营A", [{"sender": "other", "text": "你好"}]))
    assert page.sent_messages in (
        ["你好可以看看简历吗"],
        ["你好，方便发一份简历过来吗"],
    )
    assert page.resume_requests == 1

    _, page = run_case(
        conversation("外部财务产品顾问", [{"sender": "other", "text": "你好"}])
    )
    assert page.sent_messages == ["你好，方便发一份简历过来吗"]
    assert page.resume_requests == 1


def test_direct_resume_candidate_rejection_skips_without_requesting_resume() -> None:
    """候选人明确拒绝时，直求简历岗位也不能继续求简历。"""

    state, page = run_case(
        conversation("运营A", [{"sender": "other", "text": "你好，职位不太合适，谢谢关注！"}])
    )

    assert state["next_action"] == "skip"
    assert state["stage"] == "candidate_rejected"
    assert page.sent_messages == []
    assert page.resume_requests == 0


def test_ai_basic_rejects_single_rest_without_downloading_existing_attachment() -> None:
    """AI 基础条件拒绝要先跳过，不能因页面已有附件简历而下载。"""

    state, page = run_case(
        conversation(
            "AI应用开发实习生",
            [
                {"sender": "me", "text": "基础条件确认话术"},
                {"sender": "other", "text": "不好意思，不太考虑单休[握手]"},
            ],
            has_attachment_card=True,
            resume_bytes=b"%PDF-1.7\nbody\n%%EOF",
        )
    )

    assert state["next_action"] == "skip"
    assert state["stage"] == "candidate_rejected"
    assert page.sent_messages == []
    assert page.resume_requests == 0


def test_job51_seen_keys_survive_label_changes() -> None:
    """A candidate already processed in this run is deduped beyond volatile row labels."""

    first = _seen_keys_for_processed_item(
        {"id": "row-1", "label": "Candidate 09:30 已投"},
        {
            "conversationId": "conv-1",
            "sessionId": "session-1",
            "candidate": {"name": "Candidate", "applied_position": "DirectRole"},
            "job": "DirectRole",
            "recentMessagesFingerprint": "fp-1",
        },
    )
    second = _seen_keys_for_processed_item(
        {"id": "row-1", "label": "Candidate 09:31 新招呼"},
        {
            "conversationId": "conv-1",
            "sessionId": "session-1",
            "candidate": {"name": "Candidate", "applied_position": "DirectRole"},
            "job": "DirectRole",
            "recentMessagesFingerprint": "fp-1",
        },
    )

    assert first & second
    assert "session:session-1" in first


def test_job51_find_candidate_row_skips_slow_virtual_rows() -> None:
    """A stale virtual-list row must not block matching the next real unread row."""

    slow = SlowRow(row_id="slow", label="", fail_text=True)
    target = SlowRow(row_id="target", label="Candidate B")
    adapter = RowAdapter([slow, target])

    row = asyncio.run(
        _find_candidate_row(
            adapter,
            Platform.JOB51,
            {"id": "", "label": "Candidate B", "index": 0},
        )
    )

    assert row is target


def test_job51_processing_uses_guarded_dom_open_without_native_row_click(
    monkeypatch,
) -> None:
    """Unread processing should not use native 51job row clicks."""

    page = GuardedProcessingClickPage(
        conversations=[
            {
                **conversation(
                    "销售管培生",
                    [{"sender": "me", "text": "已回复"}],
                    label="已回复候选人 [送达]",
                ),
                "id": "skip-conv",
            },
            {
                **conversation(
                    "AI应用开发实习生",
                    [{"sender": "other", "text": "您好，我想进一步沟通"}],
                    label="候选人A AI应用开发实习生",
                ),
                "id": "target-conv",
            },
        ]
    )
    adapter = Job51Adapter(page, owner="宋峰峰", dry_run=True)
    monkeypatch.setattr(
        "scripts.platform_once_common.build_persistence_from_settings",
        lambda: (None, None),
    )

    summaries = asyncio.run(_process(adapter, Platform.JOB51, 1))

    assert len(summaries) == 1
    assert summaries[0]["action"] == "ask_basic_conditions"
    assert page.native_row_clicks == 0
    assert page.guarded_dom_clicks == 1
    assert page.selected_index == 1


def test_job51_cleanup_resume_overlays_closes_export_dialog() -> None:
    """The page cleanup closes stale preview/export overlays before the next row click."""

    page = FakePage(
        conversations=[
            {
                **conversation("SalesRole", [{"sender": "other", "text": "hello"}]),
                "online_resume_opened": True,
                "export_dialog_open": True,
            }
        ]
    )

    result = asyncio.run(cleanup_resume_overlays(page))

    assert result["closed"] >= 1
    assert page.current_conversation().get("online_resume_opened") is False
    assert page.current_conversation().get("export_dialog_open") is False


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


def test_job51_attachment_without_download_link_blocks_without_request() -> None:
    """附件卡存在但真实下载链接缺失时，明确 blocked，不继续点求简历。"""

    page = FakePage(
        conversations=[
            conversation(
                "B端社交媒体运营",
                [{"sender": "other", "text": "我已投递"}],
                has_attachment_card=True,
            )
        ]
    )
    adapter = Job51Adapter(page, owner="和新红")

    result = asyncio.run(adapter.request_resume())

    assert result["blocked"] is True
    assert result["downloaded"] is False
    assert result["requested"] is False
    assert page.resume_requests == 0


def test_job51_attachment_preview_uses_dom_fallback_when_click_is_intercepted() -> None:
    """51job 底部快捷回复遮挡附件卡时，用 DOM fallback 点开预览。"""

    page = InterceptedAttachmentPage()

    opened = asyncio.run(_open_attachment_resume_preview(page))  # type: ignore[arg-type]

    assert opened is True
    assert page.dom_clicked is True


def test_job51_does_not_download_resume_before_candidate_qualifies() -> None:
    """51job 看见附件不等于立刻下载，必须先走到业务上的求简历步骤。"""

    state, page = run_case(
        conversation(
            "销售管培生",
            [{"sender": "other", "text": "你好"}],
            has_attachment_card=True,
            resume_bytes=b"%PDF-1.7\nbody\n%%EOF",
        )
    )
    assert state["next_action"] == "ask_screening"
    assert "result" not in state["decision"]
    assert page.resume_requests == 0


def test_job51_downloads_top_right_online_resume_after_screening_accept() -> None:
    """筛选通过后，51job 无附件时优先点右上角在线简历下载。"""

    state, page = run_case(
        conversation(
            "销售管培生",
            [
                {"sender": "me", "text": "你是否接受出差？"},
                {"sender": "other", "text": "可以接受"},
            ],
            online_resume_bytes=b"%PDF-1.7\nbody\n%%EOF",
            online_resume_filename="候选人_销售管培生.pdf",
        )
    )
    result = state["decision"]["result"]
    assert state["next_action"] == "request_resume"
    assert result["downloaded"] is True
    assert result["resumeReceived"] is True
    assert page.resume_requests == 0
    assert page.resume_preview_closes == 1


def test_job51_downloads_online_resume_by_save_icon_after_screening_accept() -> None:
    """在线简历无 href 时，点击右上角存储卡图标捕获下载。"""

    state, page = run_case(
        conversation(
            "销售管培生",
            [
                {"sender": "me", "text": "你是否接受出差？"},
                {"sender": "other", "text": "可以接受"},
            ],
            online_resume_download_bytes=b"%PDF-1.7\nbody\n%%EOF",
            online_resume_filename="候选人_销售管培生.pdf",
        )
    )
    result = state["decision"]["result"]
    assert state["next_action"] == "request_resume"
    assert result["downloaded"] is True
    assert result["resumeReceived"] is True
    assert page.resume_requests == 0
    assert page.resume_preview_closes == 1


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


class RowAdapter:
    def __init__(self, rows: list[SlowRow]) -> None:
        self.page = RowPage(rows)


class SlowJob51ChatPage:
    """Simulates a logged-in chat tab whose shell selectors are still loading."""

    def __init__(self) -> None:
        self.url = "https://ehire.51job.com/Revision/chat/?rt=1782868459257"
        self.body_text = "加载中"
        self.clicks: list[str] = []
        self.gotos: list[str] = []
        self.shell_ready = False

    async def text(self, selector: str | None = None) -> str:
        _ = selector
        return self.body_text

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> bool:
        _ = timeout_ms
        if self.shell_ready and selector in {
            "#conversation-list .list-item",
            "#drop-area.input-textarea_self",
            "label.el-checkbox.btn.unread-checkbox",
        }:
            return True
        return selector == "#sensor_talentcommunicate"

    async def click(self, selector: str, timeout_ms: int | None = None) -> bool:
        _ = timeout_ms
        self.clicks.append(selector)
        if selector == "#sensor_talentcommunicate":
            self.url = "https://app.51job.com/51job/"
        return True

    async def goto(self, url: str) -> None:
        self.gotos.append(url)
        self.url = url
        self.body_text = "人才沟通 全部职位 未读"
        self.shell_ready = True


class DelayedJob51ContextPage:
    """Simulates a live CDP page whose DOM context settles after a click."""

    def __init__(self, contexts: list[dict[str, object]]) -> None:
        self.contexts = contexts
        self.dom_context_reads = 0

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        _ = arg
        if script in {"job51.opened_candidate_state", "job51.read_chat_context"}:
            return {}
        index = min(self.dom_context_reads, len(self.contexts) - 1)
        self.dom_context_reads += 1
        return self.contexts[index]


class BatchPanelDomContextPage:
    """Simulates a live 51job batch panel evaluated through READ_CHAT_CONTEXT_JS."""

    batch_label = "\n".join(
        [
            "沟通职位：膨润土销售人员",
            "求职意向：15000-20000/月",
            "上海,杭州,南京",
            "郭超",
            "1小时前活跃",
            "55岁",
            "24年 | 大专 | 上海-嘉定区",
            "你好，简历已投递，期待回复~",
        ]
    )

    def __init__(self) -> None:
        self.extension_reads = 0
        self.dom_reads = 0

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        _ = arg
        if script == "job51.read_chat_context":
            self.extension_reads += 1
            return {}
        if script == READ_CHAT_CONTEXT_JS:
            self.dom_reads += 1
            if "batch-chat-panel" not in script or "item-container-message" not in script:
                return {
                    "id": self.batch_label,
                    "label": self.batch_label,
                    "name": "郭超",
                    "position": "膨润土销售人员",
                    "messages": [],
                    "latest_message": "",
                    "unread_count": 1,
                }
            return {
                "id": self.batch_label,
                "label": self.batch_label,
                "name": "郭超",
                "position": "膨润土销售人员",
                "messages": [
                    {
                        "sender": "candidate",
                        "text": "你好，简历已投递，期待回复~",
                        "rawText": "你好，简历已投递，期待回复~",
                    }
                ],
                "latest_message": "你好，简历已投递，期待回复~",
                "unread_count": 1,
            }
        return {}


class GuardedPreflightClickPage(FakePage):
    """Position filter clicks simulate opening app tabs unless the guard is installed."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.app_download_popups = 0
        self.app_download_blocker_installed = False
        self.context_popup_blocker_installed = False

    async def install_url_popup_blocker(self, blocked_url_part: str) -> dict[str, object]:
        if blocked_url_part == "app.51job.com/51job":
            self.context_popup_blocker_installed = True
        return {"installed": self.context_popup_blocker_installed}

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if "job51AppDownloadBlockerInstalled" in script:
            self.app_download_blocker_installed = True
            return {"installed": True, "source": "fake_page"}
        return await super().eval_js(script, arg)

    async def handle_element_click(self, element):  # type: ignore[no-untyped-def]
        if "position-menu" in element.selector or "menu-item-all" in element.selector:
            if not self.app_download_blocker_installed:
                self.app_download_popups += 1
        await super().handle_element_click(element)


class GuardedProcessingClickPage(GuardedPreflightClickPage):
    """Native thread clicks are unsafe; guarded DOM clicks are acceptable."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.native_row_clicks = 0
        self.guarded_dom_clicks = 0

    async def handle_element_click(self, element):  # type: ignore[no-untyped-def]
        if element.selector.startswith("conversation:"):
            self.native_row_clicks += 1
        await super().handle_element_click(element)

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if "thread_row_not_found" in script and "#conversation-list .list-item" in script:
            if not self.app_download_blocker_installed:
                self.app_download_popups += 1
            payload = arg if isinstance(arg, dict) else {}
            self.selected_index = int(payload.get("index") or 0)
            self.guarded_dom_clicks += 1
            return {"clicked": True, "source": "fake_guarded_dom_click"}
        return await super().eval_js(script, arg)


class InterceptedAttachmentPage:
    """Simulates a 51job attachment card covered by the quick-reply bar."""

    def __init__(self) -> None:
        self.dom_clicked = False

    async def query_all(self, selector: str) -> list[InterceptedAttachmentElement]:
        if ".resume-element .info-content-item.file-item" in selector:
            return [InterceptedAttachmentElement()]
        return []

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        _ = arg
        if "info-content-item.file-item" in script:
            self.dom_clicked = True
            return {"clicked": True, "source": "dom_attachment_card"}
        if "annex-resume" in script:
            return {"found": self.dom_clicked, "href": "blob:resume" if self.dom_clicked else ""}
        return {}


class InterceptedAttachmentElement:
    async def click(self, timeout_ms: int | None = None) -> None:
        _ = timeout_ms
        raise TimeoutError("quick reply intercepts pointer events")

    async def text(self) -> str:
        return "附件简历"

    async def attr(self, name: str) -> str | None:
        _ = name
        return None


class RowPage:
    def __init__(self, rows: list[SlowRow]) -> None:
        self.rows = rows

    async def query_all(self, selector: str) -> list[SlowRow]:
        _ = selector
        return self.rows


class SlowRow:
    def __init__(self, *, row_id: str, label: str, fail_text: bool = False) -> None:
        self.row_id = row_id
        self.label = label
        self.fail_text = fail_text

    async def attr(self, name: str) -> str | None:
        return self.row_id if name == "id" else None

    async def text(self) -> str:
        if self.fail_text:
            raise TimeoutError("virtual row text timed out")
        return self.label


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
    has_attachment_card: bool = False,
    resume_bytes: bytes | None = None,
    resume_href: str = "",
    resume_href_bytes: bytes | None = None,
    online_resume_bytes: bytes | None = None,
    online_resume_download_bytes: bytes | None = None,
    online_resume_href: str = "",
    online_resume_href_bytes: bytes | None = None,
    online_resume_filename: str = "",
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
        "has_attachment_card": has_attachment_card,
        "resume_bytes": resume_bytes,
        "resume_href": resume_href,
        "resume_href_bytes": resume_href_bytes,
        "online_resume_bytes": online_resume_bytes,
        "online_resume_download_bytes": online_resume_download_bytes,
        "online_resume_href": online_resume_href,
        "online_resume_href_bytes": online_resume_href_bytes,
        "online_resume_filename": online_resume_filename,
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
            "AI应用开发实习生": {
                "category": "ai_app_intern",
                "initialCommonPhrase": "基础条件确认话术",
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
