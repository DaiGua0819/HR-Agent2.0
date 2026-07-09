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
from app.platforms.job51 import actions_resume_close
from app.platforms.job51 import dom_scripts as job51_dom_scripts
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
    _open_online_resume_preview,
    resume_download_suitability_guard,
    resume_identity_guard,
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

from scripts import platform_once_common


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


def test_job51_find_next_thread_uses_parsed_row_identity_when_attrs_missing() -> None:
    """Real 51job rows expose name/job in parsed state, not as DOM attributes."""

    label = (
        "3\n卢怡丞 国际业务管培生\n17:43\n"
        "[新招呼] 您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。"
    )
    page = Job51RowsWithoutIdentityAttrsPage(
        label=label,
        name="卢怡丞",
        position="国际业务管培生",
    )

    ref = asyncio.run(find_next_thread(page, owner="和新红"))

    assert ref is not None
    assert ref.conversation_id == label
    assert page.last_expected["name"] == "卢怡丞"
    assert page.last_expected["position"] == "国际业务管培生"
    assert page.row_clicked is True


def test_job51_normalize_unread_rows_infers_name_from_plain_label() -> None:
    """51job unread rows may only expose candidate identity in the visible label."""

    rows = _normalize_unread_rows(
        [
            {
                "index": 0,
                "id": "",
                "label": (
                    "1\n王欣睿\n15:05\n"
                    "您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。"
                ),
                "name": "",
                "position": "",
                "latestMessage": "",
                "unreadCount": 1,
            }
        ]
    )

    assert rows[0]["name"] == "王欣睿"
    assert rows[0]["latest_message"] == "您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。"


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


def test_job51_verify_opened_candidate_prefers_right_header_identity() -> None:
    """51job should trust the opened right-side candidate header, not the first left row."""

    page = RightHeaderIdentityPage(
        right_header={
            "opened": True,
            "source": "right_header",
            "actual": {
                "name": "鲍女士",
                "position": "外部财务产品顾问",
                "label": "鲍女士 女 53岁 外部财务产品顾问",
            },
        },
        fallback_context={
            "name": "石晓浩",
            "position": "AI应用开发工程师",
            "label": "石晓浩 AI应用开发工程师\n[新招呼] 您好",
        },
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {"label": "鲍女士 外部财务产品顾问", "name": "鲍女士", "position": "外部财务产品顾问"},
            chat_ready=True,
            timeout_ms=50,
            interval_ms=0,
        )
    )

    assert opened["opened"] is True
    assert opened["source"] == "right_header"
    assert opened["actual"]["name"] == "鲍女士"
    assert page.right_header_reads == 1


def test_job51_verify_opened_candidate_accepts_right_header_name_from_label() -> None:
    """When row attrs are missing, the expected name can come from the left label."""

    page = RightHeaderIdentityPage(
        right_header={
            "opened": False,
            "reason": "candidate_identity_mismatch",
            "source": "right_header",
            "chatReady": True,
            "actual": {
                "name": "王欣睿",
                "position": "",
                "label": "王欣睿\n沟通职位：",
                "headerText": "王欣睿\n沟通职位：",
                "source": "right_header",
            },
        },
        fallback_context={},
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {
                "label": (
                    "1\n王欣睿\n15:05\n"
                    "您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。"
                ),
                "name": "",
                "position": "",
            },
            chat_ready=True,
            timeout_ms=0,
            interval_ms=0,
        )
    )

    assert opened["opened"] is True
    assert opened["actual"]["name"] == "王欣睿"


def test_job51_verify_opened_candidate_reports_right_header_mismatch_source() -> None:
    """51job identity mismatch diagnostics should expose that the right header was read."""

    page = RightHeaderIdentityPage(
        right_header={
            "opened": False,
            "reason": "candidate_identity_mismatch",
            "source": "right_header",
            "actual": {
                "name": "田杰",
                "position": "外部财务产品顾问",
                "label": "田杰 外部财务产品顾问",
            },
        },
        fallback_context={},
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {"label": "鲍女士 外部财务产品顾问", "name": "鲍女士", "position": "外部财务产品顾问"},
            chat_ready=True,
            timeout_ms=0,
            interval_ms=0,
        )
    )

    assert opened["opened"] is False
    assert opened["reason"] == "candidate_identity_mismatch"
    assert opened["actual"]["source"] == "right_header"
    assert opened["actual"]["name"] == "田杰"


def test_job51_verify_opened_candidate_rejects_position_only_match_without_name() -> None:
    """Same-position rows are unsafe unless the right header confirms the candidate name."""

    page = RightHeaderIdentityPage(
        right_header={
            "opened": False,
            "reason": "candidate_identity_mismatch",
            "source": "right_header",
            "chatReady": True,
            "actual": {
                "name": "",
                "position": "AI PM",
                "label": "沟通职位：AI PM",
                "headerText": "沟通职位：AI PM",
                "source": "right_header",
            },
        },
        fallback_context={},
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {"label": "Target Candidate\nAI PM", "name": "Target Candidate", "position": "AI PM"},
            chat_ready=True,
            timeout_ms=0,
            interval_ms=0,
        )
    )

    assert opened["opened"] is False
    assert opened["reason"] == "candidate_identity_mismatch"


def test_job51_verify_opened_candidate_uses_context_when_header_has_only_position() -> None:
    """51job detail panes may expose position only; context can confirm the selected name."""

    page = RightHeaderIdentityPage(
        right_header={
            "opened": False,
            "reason": "candidate_identity_mismatch",
            "source": "right_header",
            "chatReady": True,
            "actual": {
                "name": "",
                "position": "AI 产品经理",
                "label": "暂未填写工作经历\n沟通职位：\nAI 产品经理",
                "headerText": "暂未填写工作经历\n沟通职位：\nAI 产品经理",
                "source": "right_header",
            },
        },
        fallback_context={
            "name": "冯先生",
            "position": "AI 产品经理",
            "label": "冯先生\n男 | 24岁 | 硕士\n沟通职位：\nAI 产品经理",
            "source": "right_header",
        },
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {
                "label": (
                    "冯先生 AI 产品经理\n"
                    "[新招呼] 您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。"
                ),
                "name": "冯先生",
                "position": "AI 产品经理",
                "latest_message": (
                    "[新招呼] 您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。"
                ),
            },
            chat_ready=True,
            timeout_ms=0,
            interval_ms=0,
        )
    )

    assert opened["opened"] is True
    assert opened["actual"]["name"] == "冯先生"
    assert opened["matchType"] == "exact_name_match"
    assert page.fallback_reads == 1


def test_job51_verify_opened_candidate_ignores_resume_detail_badges_as_name() -> None:
    """51job resume details may expose education badges, not the candidate name."""

    for badge in ("留学", "双一流"):
        page = RightHeaderIdentityPage(
            right_header={
                "opened": False,
                "reason": "candidate_identity_mismatch",
                "source": "right_header",
                "chatReady": True,
                "actual": {
                    "name": badge,
                    "position": "B端社交媒体运营",
                    "label": (
                        "暂未填写工作经历\n"
                        "2021.04 - 2026.03\n"
                        "京都精华大学\n"
                        "|本科\n"
                        "|雕塑\n"
                        f"{badge}\n"
                        "沟通职位：\n"
                        "B端社交媒体运营\n"
                        "求职意向：\n"
                        "日语老师"
                    ),
                    "headerText": (
                        "暂未填写工作经历\n"
                        "2021.04 - 2026.03\n"
                        "京都精华大学\n"
                        "|本科\n"
                        "|雕塑\n"
                        f"{badge}\n"
                        "沟通职位：\n"
                        "B端社交媒体运营\n"
                        "求职意向：\n"
                        "日语老师"
                    ),
                    "source": "right_header",
                },
            },
            fallback_context={
                "name": "刘先生",
                "position": "B端社交媒体运营",
                "label": (
                    "刘先生\n"
                    "沟通职位：B端社交媒体运营\n"
                    "[新招呼] 你好，简历已投递，期待回复~"
                ),
                "source": "left_selected_row",
            },
        )

        opened = asyncio.run(
            verify_opened_candidate(
                page,
                {
                    "label": (
                        "3\n刘先生 B端社交媒体运营\n07/02\n"
                        "[新招呼] 你好，简历已投递，期待回复~"
                    ),
                    "name": "刘先生",
                    "position": "B端社交媒体运营",
                    "latest_message": "[新招呼] 你好，简历已投递，期待回复~",
                },
                chat_ready=True,
                timeout_ms=0,
                interval_ms=0,
            )
        )

        assert opened["opened"] is True
        assert opened["actual"]["name"] == "刘先生"
        assert opened["actual"]["source"] == "left_selected_row"
        assert page.fallback_reads == 1


def test_job51_verify_opened_candidate_accepts_anonymous_name_with_message_evidence() -> None:
    """51job anonymous left-list names can resolve to right-header real names safely."""

    latest = "对方向你发送了简历"
    page = RightHeaderIdentityPage(
        right_header={
            "opened": False,
            "reason": "candidate_identity_mismatch",
            "source": "right_header",
            "chatReady": True,
            "actual": {
                "name": "王娜娜",
                "position": "国际业务管培生",
                "label": "王娜娜\n沟通职位：国际业务管培生\n在线简历\n附件简历\n对方向你发送了简历",
                "headerText": (
                    "王娜娜\n沟通职位：国际业务管培生\n在线简历\n附件简历\n对方向你发送了简历"
                ),
                "source": "right_header",
            },
        },
        fallback_context={},
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {
                "label": f"3\n王女士 国际业务管培生\n17:57\n[新招呼] {latest}",
                "name": "王女士",
                "position": "国际业务管培生",
                "latest_message": f"[新招呼] {latest}",
            },
            chat_ready=True,
            timeout_ms=0,
            interval_ms=0,
        )
    )

    assert opened["opened"] is True
    assert opened["matchType"] == "anonymous_name_resolved"
    assert "latest_message_match" in opened["evidence"] or "resume_evidence" in opened["evidence"]


def test_job51_verify_opened_candidate_accepts_right_header_anonymous_name() -> None:
    """51job right headers may hide a real left-list name as same-surname anonymous title."""

    page = RightHeaderIdentityPage(
        right_header={
            "opened": False,
            "reason": "candidate_identity_mismatch",
            "source": "right_header",
            "chatReady": True,
            "actual": {
                "name": "田先生",
                "position": "AI 产品经理",
                "label": "田先生\n沟通职位：\nAI 产品经理\n求职意向：\nAI产品经理",
                "headerText": "田先生\n沟通职位：\nAI 产品经理\n求职意向：\nAI产品经理",
                "source": "right_header",
            },
        },
        fallback_context={},
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {
                "label": (
                    "1\n田治国 AI 产品经理\n11:37\n[新招呼] "
                    "您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。"
                ),
                "name": "田治国",
                "position": "AI 产品经理",
                "latest_message": (
                    "[新招呼] 您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。"
                ),
            },
            chat_ready=True,
            timeout_ms=0,
            interval_ms=0,
        )
    )

    assert opened["opened"] is True
    assert opened["matchType"] == "anonymous_name_resolved"
    assert "right_header_anonymous" in opened["evidence"]


def test_job51_verify_opened_candidate_rejects_anonymous_name_without_message_evidence() -> None:
    """Same surname and same position are not enough for anonymous 51job rows."""

    page = RightHeaderIdentityPage(
        right_header={
            "opened": False,
            "reason": "candidate_identity_mismatch",
            "source": "right_header",
            "chatReady": True,
            "actual": {
                "name": "王娜娜",
                "position": "国际业务管培生",
                "label": "王娜娜\n沟通职位：国际业务管培生\n英语翻译\n6-7千/月",
                "headerText": "王娜娜\n沟通职位：国际业务管培生\n英语翻译\n6-7千/月",
                "source": "right_header",
            },
        },
        fallback_context={},
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {
                "label": "3\n王女士 国际业务管培生\n17:57\n[新招呼] 对方向你发送了简历",
                "name": "王女士",
                "position": "国际业务管培生",
                "latest_message": "[新招呼] 对方向你发送了简历",
            },
            chat_ready=True,
            timeout_ms=0,
            interval_ms=0,
        )
    )

    assert opened["opened"] is False
    assert opened["matchType"] == "position_only_match"


def test_job51_verify_opened_candidate_accepts_anonymous_name_after_confirmed_click() -> None:
    """A high-confidence target-row click is evidence for anonymous left-list names."""

    page = RightHeaderIdentityPage(
        right_header={
            "opened": False,
            "reason": "candidate_identity_mismatch",
            "source": "right_header",
            "chatReady": True,
            "actual": {
                "name": "李泽文",
                "position": "B端社交媒体运营",
                "label": (
                    "李泽文\n男 | 27岁 | 暂无工作经验 | 硕士 | 国外\n"
                    "沟通职位：\nB端社交媒体运营\n求职意向：\n新媒体运营"
                ),
                "headerText": (
                    "李泽文\n男 | 27岁 | 暂无工作经验 | 硕士 | 国外\n"
                    "沟通职位：\nB端社交媒体运营\n求职意向：\n新媒体运营"
                ),
                "source": "right_header",
            },
        },
        fallback_context={},
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {
                "label": (
                    "3\n李先生 B端社交媒体运营\n07/01\n"
                    "[新招呼] 您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。"
                ),
                "name": "李先生",
                "position": "B端社交媒体运营",
                "latest_message": (
                    "[新招呼] 您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。"
                ),
                "_identity_click": {
                    "clicked": True,
                    "source": "identity_dom_click",
                    "score": 185,
                    "label": (
                        "3\n李先生 B端社交媒体运营\n07/01\n"
                        "[新招呼] 您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。"
                    ),
                    "name": "李先生",
                    "position": "B端社交媒体运营",
                    "latestMessage": (
                        "[新招呼] 您好，我对贵公司的这个职位很感兴趣，希望可以进一步沟通。"
                    ),
                },
            },
            chat_ready=True,
            timeout_ms=0,
            interval_ms=0,
        )
    )

    assert opened["opened"] is True
    assert opened["matchType"] == "anonymous_name_resolved"
    assert "confirmed_identity_click" in opened["evidence"]


def test_job51_verify_opened_candidate_rejects_anonymous_name_with_only_surname() -> None:
    """Anonymous left-list names need a full same-surname right-header name."""

    latest = "对方向你发送了简历"
    page = RightHeaderIdentityPage(
        right_header={
            "opened": False,
            "reason": "candidate_identity_mismatch",
            "source": "right_header",
            "chatReady": True,
            "actual": {
                "name": "王",
                "position": "国际业务管培生",
                "label": f"王\n沟通职位：国际业务管培生\n{latest}",
                "headerText": f"王\n沟通职位：国际业务管培生\n{latest}",
                "source": "right_header",
            },
        },
        fallback_context={},
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {
                "label": f"王女士\n国际业务管培生\n[新招呼] {latest}",
                "name": "王女士",
                "position": "国际业务管培生",
                "latest_message": f"[新招呼] {latest}",
            },
            chat_ready=True,
            timeout_ms=0,
            interval_ms=0,
        )
    )

    assert opened["opened"] is False
    assert opened["matchType"] == "identity_mismatch"


def test_job51_verify_opened_candidate_rejects_same_name_with_different_position() -> None:
    """A same display name is unsafe when the right-header position is different."""

    page = RightHeaderIdentityPage(
        right_header={
            "opened": False,
            "reason": "candidate_identity_mismatch",
            "source": "right_header",
            "chatReady": True,
            "actual": {
                "name": "王女士",
                "position": "B端社交媒体运营",
                "label": "王女士\n沟通职位：B端社交媒体运营",
                "headerText": "王女士\n沟通职位：B端社交媒体运营",
                "source": "right_header",
            },
        },
        fallback_context={},
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {
                "label": "3\n王女士 国际业务管培生\n17:57\n[新招呼] 对方向你发送了简历",
                "name": "王女士",
                "position": "国际业务管培生",
                "latest_message": "[新招呼] 对方向你发送了简历",
            },
            chat_ready=True,
            timeout_ms=0,
            interval_ms=0,
        )
    )

    assert opened["opened"] is False
    assert opened["matchType"] == "identity_mismatch"


def test_job51_verify_opened_candidate_rejects_city_as_name() -> None:
    """A city parsed as the right-header name must not pass identity verification."""

    page = RightHeaderIdentityPage(
        right_header={
            "opened": False,
            "reason": "candidate_identity_mismatch",
            "source": "right_header",
            "chatReady": True,
            "actual": {
                "name": "上海",
                "position": "国际业务管培生",
                "label": "沟通职位：国际业务管培生\n求职意向：6000-7000/月\n上海\n王娜娜",
                "headerText": "沟通职位：国际业务管培生\n求职意向：6000-7000/月\n上海\n王娜娜",
                "source": "right_header",
            },
        },
        fallback_context={},
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {
                "label": "3\n王女士 国际业务管培生\n17:57\n[新招呼] 对方向你发送了简历",
                "name": "王女士",
                "position": "国际业务管培生",
                "latest_message": "[新招呼] 对方向你发送了简历",
            },
            chat_ready=True,
            timeout_ms=0,
            interval_ms=0,
        )
    )

    assert opened["opened"] is False
    assert opened["matchType"] == "identity_mismatch"


def test_job51_opened_candidate_state_ignores_resume_card_status_as_name() -> None:
    """The DOM identity script must not treat chat-card status text as a name."""

    script = job51_dom_scripts.OPENED_CANDIDATE_STATE_JS

    assert "对方已投递" in script
    assert "暂未填写工作经历" in script
    assert "拒绝" in script
    assert "同意" in script
    assert "查看更多" in script
    assert "对方撤回了一条消息" in script
    assert "已读" in script
    assert "可提升求职者" in script
    assert "已邀请对方投递" in script
    assert "的简历" in script
    assert "parts[index + 1]" in script
    assert "readHeaderName(clean(text(el)).split" in script


def test_job51_read_chat_context_prefers_selected_row_over_resume_detail_name() -> None:
    """Chat context should not let resume detail school/work lines override selected row names."""

    script = job51_dom_scripts.READ_CHAT_CONTEXT_JS

    assert "暂未填写工作经历" in script
    assert "查看更多" in script
    assert "对方撤回了一条消息" in script
    assert "已读" in script
    assert "可提升求职者" in script
    assert "已邀请对方投递" in script
    assert "const name = selectedName || rightHeaderName" in script


def test_job51_verify_opened_candidate_reads_first_header_line_before_talent_radar() -> None:
    """The right header first line is the candidate name; 人才罗盘 is not a name."""

    page = TalentRadarRightHeaderPage()

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {
                "label": "姚亚回 投资交易策略研究员（量化与市场情绪方向）",
                "name": "姚亚回",
                "position": "投资交易策略研究员（量化与市场情绪方向）",
            },
            chat_ready=True,
            timeout_ms=0,
            interval_ms=0,
        )
    )

    assert opened["opened"] is True
    assert opened["actual"]["name"] == "姚亚回"
    assert opened["actual"]["source"] == "right_header"


def test_job51_verify_opened_candidate_accepts_ellipsis_position() -> None:
    """51job 左侧岗位截断时，右侧全称岗位不应被判定为岗位冲突。"""

    page = TalentRadarRightHeaderPage()

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {
                "label": "姚亚回 投资交易策略...与市场情绪方向）",
                "name": "姚亚回",
                "position": "投资交易策略...与市场情绪方向）",
            },
            chat_ready=True,
            timeout_ms=0,
            interval_ms=0,
        )
    )

    assert opened["opened"] is True
    assert opened["matchType"] == "exact_name_match"
    assert "position_match" in opened["evidence"]


def test_job51_verify_opened_candidate_recovers_name_from_resume_card_label() -> None:
    """51job may expose a chat resume card where the first name-like line is the job title."""

    label = "\n".join(
        [
            "06-24 11:12",
            "您好，我是现大一的学生，希望能得到贵公司的实习机会",
            "07-05 16:57",
            "国际业务管培生",
            "6,000-10,000/月",
            "不限城市 | 无需工作经验 | 本科 | 英语·读写熟练",
            "浙江长安仁恒科技股份有限公司上海",
            "对方已投递",
            "劳嘉铃的简历",
            "您好，这是我的简历，请查收~",
            "在线简历",
        ]
    )
    page = RightHeaderIdentityPage(
        right_header={
            "opened": False,
            "reason": "candidate_identity_mismatch",
            "source": "right_header",
            "chatReady": True,
            "actual": {
                "name": "国际业务管培生",
                "position": "",
                "label": label,
                "headerText": label,
                "source": "right_header",
            },
        },
        fallback_context={},
    )

    opened = asyncio.run(
        verify_opened_candidate(
            page,
            {
                "label": "3\n劳嘉铃 国际业务管培生\n07/05\n[新招呼] 对方向你发送了简历",
                "name": "劳嘉铃",
                "position": "国际业务管培生",
                "latest_message": "[新招呼] 对方向你发送了简历",
            },
            chat_ready=True,
            timeout_ms=0,
            interval_ms=0,
        )
    )

    assert opened["opened"] is True
    assert opened["actual"]["name"] == "劳嘉铃"
    assert opened["matchType"] == "exact_name_match"
    assert "resume_card_name_match" in opened["evidence"]


def test_job51_read_chat_context_script_prefers_right_header_over_first_left_row() -> None:
    """READ_CHAT_CONTEXT_JS must expose right-header identity before left-list fallback."""

    page = RightHeaderChatContextPage()

    context = asyncio.run(read_chat_context(page, owner="宋峰峰"))

    assert context.candidate.name == "鲍女士"
    assert context.candidate.applied_position == "外部财务产品顾问"
    assert page.dom_reads == 1


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


def test_job51_click_thread_by_state_relocates_by_identity_when_index_is_stale() -> None:
    """51job virtual rows can reuse indexes; identity must beat stale index."""

    page = FakePage(
        conversations=[
            {
                "id": "wrong-row",
                "name": "错误候选人",
                "position": "国际业务管培生",
                "label": "错误候选人 国际业务管培生",
                "latest_message": "你好",
                "unread_count": 1,
                "messages": [{"sender": "other", "text": "你好"}],
            },
            {
                "id": "target-row",
                "name": "目标候选人",
                "position": "B端社交媒体运营",
                "label": "目标候选人 B端社交媒体运营\n简历已发送",
                "latest_message": "简历已发送",
                "unread_count": 1,
                "messages": [{"sender": "other", "text": "简历已发送"}],
            },
        ]
    )

    result = asyncio.run(
        click_thread_by_state(
            page,
            {
                "index": 0,
                "id": "",
                "label": "目标候选人\nB端社交媒体运营\n简历已发送",
                "name": "目标候选人",
                "position": "B端社交媒体运营",
                "latest_message": "简历已发送",
            },
            expected={
                "id": "",
                "label": "目标候选人\nB端社交媒体运营\n简历已发送",
                "name": "目标候选人",
                "position": "B端社交媒体运营",
                "latest_message": "简历已发送",
            },
        )
    )

    assert result["clicked"] is True
    assert page.selected_index == 1


def test_job51_click_thread_by_state_rejects_same_name_different_position() -> None:
    """Identity fallback must not click a same-name row from another job."""

    page = FakePage(
        conversations=[
            {
                "id": "wrong-job-row",
                "name": "王女士",
                "position": "B端社交媒体运营",
                "label": "王女士 B端社交媒体运营\n您好，我对贵公司的这个职位很感兴趣",
                "latest_message": "您好，我对贵公司的这个职位很感兴趣",
                "unread_count": 1,
                "messages": [{"sender": "other", "text": "您好，我对贵公司的这个职位很感兴趣"}],
            }
        ]
    )

    result = asyncio.run(
        click_thread_by_state(
            page,
            {
                "index": 0,
                "id": "",
                "label": "王女士\n国际业务管培生\n对方向你发送了简历",
                "name": "王女士",
                "position": "国际业务管培生",
                "latest_message": "对方向你发送了简历",
            },
            expected={
                "id": "",
                "label": "王女士\n国际业务管培生\n对方向你发送了简历",
                "name": "王女士",
                "position": "国际业务管培生",
                "latest_message": "对方向你发送了简历",
            },
        )
    )

    assert result["clicked"] is False
    assert result["reason"] in {"thread_identity_not_found", "thread_identity_low_confidence"}
    assert page.selected_index in {None, 0}


def test_job51_once_runner_fallback_passes_expected_identity(monkeypatch) -> None:
    """The terminal once runner must use identity fallback, not stale row indexes."""

    class Page:
        identity_clicked = False
        fallback_expected: dict[str, object] | None = None

    class Adapter:
        def __init__(self) -> None:
            self.page = Page()

    async def fake_wait_chat_ready(page, timeout_ms: int = 5000) -> bool:
        _ = page, timeout_ms
        return True

    async def fake_verify_opened_candidate(
        page,
        expected: dict[str, object],
        *,
        chat_ready: bool = False,
        **kwargs,
    ) -> dict[str, object]:
        _ = chat_ready, kwargs
        return {
            "opened": bool(page.identity_clicked),
            "reason": "" if page.identity_clicked else "candidate_identity_mismatch",
            "expected": dict(expected),
        }

    async def fake_click_thread_by_state(
        page,
        state: dict[str, object],
        *,
        expected: dict[str, object] | None = None,
        row=None,
    ) -> dict[str, object]:
        _ = state, row
        page.fallback_expected = dict(expected) if isinstance(expected, dict) else None
        if (
            expected
            and expected.get("name") == "Target Candidate"
            and expected.get("position") == "AI PM"
            and expected.get("latest_message") == "resume sent"
        ):
            page.identity_clicked = True
            return {"clicked": True, "source": "identity"}
        return {"clicked": False, "reason": "expected_identity_missing"}

    monkeypatch.setattr(
        platform_once_common.job51_chat,
        "wait_chat_ready",
        fake_wait_chat_ready,
    )
    monkeypatch.setattr(
        platform_once_common.job51_chat,
        "verify_opened_candidate",
        fake_verify_opened_candidate,
    )
    monkeypatch.setattr(
        platform_once_common.job51_chat,
        "click_thread_by_state",
        fake_click_thread_by_state,
    )

    adapter = Adapter()
    result = asyncio.run(
        platform_once_common._ensure_job51_thread_opened(
            adapter,
            {
                "index": 0,
                "id": "",
                "label": "stale virtual row",
                "name": "Target Candidate",
                "position": "AI PM",
                "latestMessage": "resume sent",
            },
            {"ok": False, "action": "job51_safe_open"},
        )
    )

    assert result["ok"] is True
    assert adapter.page.fallback_expected == {
        "id": "stale virtual row",
        "label": "stale virtual row",
        "name": "Target Candidate",
        "position": "AI PM",
        "latest_message": "resume sent",
    }


def test_job51_process_failure_summary_keeps_open_diagnostics(monkeypatch) -> None:
    """Open failures must include expected/right-header/fallback diagnostics in logs."""

    class Adapter:
        page = type("Page", (), {"reliable_actions": []})()

    class Row:
        async def text(self) -> str:
            return "Target Candidate\nAI PM\nhello"

    row_state = {
        "index": 0,
        "id": "target-row",
        "label": "Target Candidate\nAI PM\nhello",
        "name": "Target Candidate",
        "position": "AI PM",
        "latest_message": "hello",
    }
    expected = {
        "id": "target-row",
        "label": "Target Candidate\nAI PM\nhello",
        "name": "Target Candidate",
        "position": "AI PM",
        "latest_message": "hello",
    }
    opened = {
        "opened": False,
        "reason": "candidate_identity_mismatch",
        "expected": expected,
        "actual": {
            "name": "Old Candidate",
            "position": "AI PM",
            "label": "Old Candidate AI PM",
            "source": "right_header",
        },
    }
    fallback = {
        "clicked": True,
        "source": "identity_dom_click",
        "index": 4,
        "score": 102,
        "label": "Target Candidate\nAI PM\nhello",
    }

    async def fake_cleanup(page, *, phase: str):  # type: ignore[no-untyped-def]
        _ = page, phase
        return {"remaining": []}

    async def fake_candidate_rows(adapter, platform):  # type: ignore[no-untyped-def]
        _ = adapter, platform
        return [row_state]

    async def fake_find_row(adapter, platform, state):  # type: ignore[no-untyped-def]
        _ = adapter, platform, state
        return Row()

    async def fake_open_thread(adapter, state):  # type: ignore[no-untyped-def]
        _ = adapter, state
        return {
            "ok": False,
            "reason": "candidate_identity_mismatch",
            "expected": expected,
            "opened": opened,
            "fallback": fallback,
        }

    monkeypatch.setattr(
        "scripts.platform_once_common.build_persistence_from_settings",
        lambda: (None, None),
    )
    monkeypatch.setattr(platform_once_common, "_cleanup_job51", fake_cleanup)
    monkeypatch.setattr(platform_once_common, "_candidate_row_states", fake_candidate_rows)
    monkeypatch.setattr(platform_once_common, "_find_candidate_row", fake_find_row)
    monkeypatch.setattr(platform_once_common, "_open_job51_thread", fake_open_thread)

    summaries = asyncio.run(_process(Adapter(), Platform.JOB51, 1))
    decision = summaries[0]["decision"]

    assert summaries[0]["stage"] == "open_thread_failed"
    assert decision["reason"] == "candidate_identity_mismatch"
    assert decision["expected"] == expected
    assert decision["opened"] == opened
    assert decision["fallback"] == fallback


def test_job51_candidate_timeout_allows_slow_online_resume_downloads() -> None:
    """51job online resume download flows can exceed the old 90 second outer budget."""

    assert platform_once_common.PLATFORM_CANDIDATE_TIMEOUT_SECONDS >= 180


def test_job51_open_retries_same_target_when_right_header_stays_old(monkeypatch) -> None:
    """If the first click leaves the old header open, retry the same target once."""

    class Page:
        click_attempts = 0
        verify_attempts = 0

    class Adapter:
        def __init__(self) -> None:
            self.page = Page()

    async def fake_wait_chat_ready(page, timeout_ms: int = 5000) -> bool:
        _ = page, timeout_ms
        return True

    async def fake_verify_opened_candidate(
        page,
        expected: dict[str, object],
        *,
        chat_ready: bool = False,
        timeout_ms: int = 5000,
        interval_ms: int = 150,
    ) -> dict[str, object]:
        page.verify_attempts += 1
        actual_name = "Target Candidate" if page.click_attempts >= 2 else "Old Candidate"
        opened = actual_name == expected["name"]
        return {
            "opened": opened,
            "reason": "" if opened else "candidate_identity_mismatch",
            "chatReady": chat_ready,
            "expected": dict(expected),
            "actual": {
                "name": actual_name,
                "position": "AI PM",
                "label": f"{actual_name} AI PM",
                "source": "right_header",
            },
            "timeoutMs": timeout_ms,
            "intervalMs": interval_ms,
        }

    async def fake_click_thread_by_state(
        page,
        state: dict[str, object],
        *,
        expected: dict[str, object] | None = None,
        row=None,
    ) -> dict[str, object]:
        _ = state, expected, row
        page.click_attempts += 1
        return {
            "clicked": True,
            "source": "identity_dom_click",
            "index": 4,
            "score": 102,
            "label": "Target Candidate\nAI PM\nhello",
        }

    async def fake_sleep(seconds: float) -> None:
        _ = seconds

    monkeypatch.setattr(platform_once_common.job51_chat, "wait_chat_ready", fake_wait_chat_ready)
    monkeypatch.setattr(
        platform_once_common.job51_chat,
        "verify_opened_candidate",
        fake_verify_opened_candidate,
    )
    monkeypatch.setattr(
        platform_once_common.job51_chat,
        "click_thread_by_state",
        fake_click_thread_by_state,
    )
    monkeypatch.setattr(platform_once_common.asyncio, "sleep", fake_sleep)

    adapter = Adapter()
    result = asyncio.run(
        platform_once_common._ensure_job51_thread_opened(
            adapter,
            {
                "index": 4,
                "id": "target-row",
                "label": "Target Candidate\nAI PM\nhello",
                "name": "Target Candidate",
                "position": "AI PM",
                "latestMessage": "hello",
            },
            {"ok": False, "action": "job51_safe_open"},
        )
    )

    assert result["ok"] is True
    assert adapter.page.click_attempts == 2
    assert result["opened"]["actual"]["name"] == "Target Candidate"
    assert result["opened"]["timeoutMs"] == 8000
    assert result["opened"]["intervalMs"] == 200


def test_job51_find_next_thread_skips_repeated_identity_mismatch_in_session() -> None:
    """A bad virtual row should not be clicked again on the next drain iteration."""

    page = AlwaysMismatchedJob51Page()

    first = asyncio.run(find_next_thread(page, owner="和新红"))
    second = asyncio.run(find_next_thread(page, owner="和新红"))

    assert first is None
    assert second is None
    assert page.identity_click_attempts == 1


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
            "latest_message": "hello",
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


def test_job51_ai_product_manager_direct_resume_without_screening() -> None:
    """AI 产品经理在 51job 走直求简历，不发筛选题。"""

    state, page = run_case(
        conversation("AI Product Manager", [{"sender": "other", "text": "您好，我想了解岗位"}])
    )

    assert state["next_action"] == "request_resume"
    assert state["stage"] == "direct_resume"
    assert page.sent_messages in (
        ["你好，方便发一份简历过来吗"],
        ["你好，可以看看简历吗"],
    )
    assert page.resume_requests == 1


def test_job51_ai_product_manager_question_still_downloads_online_resume() -> None:
    """AI product manager direct-resume jobs must not stop on a silent question."""

    state, page = run_case(
        conversation(
            "AI Product Manager",
            [{"sender": "other", "text": "请问AI 产品经理还在招人吗？"}],
            online_resume_download_bytes=b"%PDF-1.7\nbody\n%%EOF",
            online_resume_filename="candidate.pdf",
            preview_only=True,
        )
    )

    result = state["decision"]["result"]
    assert state["next_action"] == "request_resume"
    assert state["stage"] in {
        "direct_resume",
        "resume_consent_requested",
        "resume_attachment_downloaded",
    }
    assert result["downloaded"] is True
    assert result["resumeReceived"] is True
    assert result["sourceKind"] == "online_resume"
    assert page.resume_requests == 0


def test_job51_ellipsis_position_matches_investment_direct_resume() -> None:
    """51job 列表会截断长岗位名，省略号岗位仍应命中投资岗直求简历规则。"""

    state, page = run_case(
        conversation(
            "投资交易策略...与市场情绪方向）",
            [{"sender": "other", "text": "您好，我发了简历"}],
        )
    )

    assert state["next_action"] == "request_resume"
    assert state["stage"] == "direct_resume"
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


def test_job51_processing_uses_guarded_identity_open_without_native_row_click(
    monkeypatch,
) -> None:
    """Unread processing should use guarded identity opening, not native row clicks."""

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
    assert page.guarded_identity_clicks == 1
    assert page.guarded_dom_clicks == 0
    assert page.selected_index == 1


def test_job51_processing_stops_when_resume_overlay_remains(monkeypatch) -> None:
    """A stale resume overlay must stop 51job before opening the next candidate."""

    page = GuardedProcessingClickPage(
        conversations=[
            {
                **conversation(
                    "AI搴旂敤寮€鍙戝疄涔犵敓",
                    [{"sender": "other", "text": "hello"}],
                    label="Candidate A AI搴旂敤寮€鍙戝疄涔犵敓",
                ),
                "id": "target-conv",
            }
        ]
    )
    adapter = Job51Adapter(page, owner="owner", dry_run=True)

    async def stale_cleanup(page, *, phase: str):  # type: ignore[no-untyped-def]
        _ = page, phase
        return {"closed": 0, "remaining": ["online_resume_preview"], "actions": []}

    monkeypatch.setattr(
        "scripts.platform_once_common.build_persistence_from_settings",
        lambda: (None, None),
    )
    monkeypatch.setattr(platform_once_common, "_cleanup_job51", stale_cleanup)

    summaries = asyncio.run(_process(adapter, Platform.JOB51, 1))

    assert summaries[0]["action"] == "failed"
    assert summaries[0]["stage"] == "stale_resume_overlay_not_closed"
    assert page.guarded_identity_clicks == 0


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


def test_job51_cleanup_resume_overlays_reports_remaining_overlay() -> None:
    """If a resume overlay cannot be closed, processing must see it in diagnostics."""

    page = StubbornResumeOverlayPage()

    result = asyncio.run(cleanup_resume_overlays(page))

    assert "online_resume_preview" in result["remaining"]


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


def test_job51_resume_identity_guard_blocks_wrong_candidate_pdf() -> None:
    """51job must not record a stale preview PDF under the current candidate."""

    wrong_pdf = minimal_pdf_with_text("Wrong Candidate Applied Position: AI Intern")

    result = resume_identity_guard(
        wrong_pdf,
        candidate_name="Current Candidate",
        applied_position="AI Product Manager",
    )

    assert result["blocked"] is True
    assert result["reason"] == "resume_identity_mismatch"


def test_job51_resume_identity_guard_accepts_matching_candidate_pdf() -> None:
    """Matching candidate text should allow the downloaded PDF to be saved."""

    content = minimal_pdf_with_text("Current Candidate Applied Position: Social Media Operator")

    result = save_resume_bytes(
        content,
        candidate_name="Current Candidate",
        applied_position="Social Media Operator",
        filename="51job_Wrong_Candidate_AI_Intern.pdf",
        memory=InMemoryResumeDownloadMemory(),
    )

    assert result["ok"] is True
    assert "Wrong_Candidate" not in str(result["filePath"])
    assert "Current Candidate" in str(result["filePath"])


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


def test_job51_preview_only_online_resume_uses_save_download_before_request() -> None:
    """Preview-only online resumes should be exported with the save/download layer."""

    page = OnlineResumeEntryPage(
        conversations=[
            conversation(
                "AI Product Manager",
                [{"sender": "other", "text": "已发在线简历"}],
                online_resume_download_bytes=b"%PDF-1.7\nbody\n%%EOF",
                online_resume_filename="candidate.pdf",
                preview_only=True,
            )
        ]
    )
    adapter = Job51Adapter(page, owner="和新红")

    result = asyncio.run(adapter.request_resume())

    assert result["requested"] is False
    assert result["downloaded"] is True
    assert result["resumeReceived"] is True
    assert result["sourceKind"] == "online_resume"
    assert page.resume_requests == 0
    assert page.message_card_clicks == 1


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


def test_job51_attachment_preview_falls_back_to_top_right_annex_entry() -> None:
    """聊天附件入口不可用时，右上角附件简历入口也能打开预览。"""

    page = TopRightAttachmentPage()

    opened = asyncio.run(_open_attachment_resume_preview(page))  # type: ignore[arg-type]

    assert opened is True
    assert page.top_right_clicked is True


def test_job51_attachment_preview_retries_dom_fallback_when_legacy_click_not_verified() -> None:
    """旧页面脚本声称已点击但没打开预览时，继续执行新 DOM fallback。"""

    page = LegacyAttachmentClickNotVerifiedPage()

    opened = asyncio.run(_open_attachment_resume_preview(page))  # type: ignore[arg-type]

    assert opened is True
    assert page.legacy_clicked is True
    assert page.top_right_clicked is True


def test_job51_attachment_dom_script_prefers_message_card_before_header_annex() -> None:
    """真实页右上角附件可能卡加载，DOM fallback 应先点聊天卡片。"""

    script = job51_dom_scripts.CLICK_ATTACHMENT_RESUME_JS

    assert "messageCandidates" in script
    assert "headerCandidates" in script
    assert script.index("messageCandidates") < script.index("headerCandidates")


def test_job51_attachment_failure_falls_back_to_online_resume_download() -> None:
    """附件入口打不开但在线简历可用时，不应直接 blocked。"""

    state, page = run_case(
        conversation(
            "销售管培生",
            [
                {"sender": "me", "text": "你是否接受出差？"},
                {"sender": "other", "text": "可以接受"},
            ],
            has_attachment_card=True,
            online_resume_bytes=b"%PDF-1.7\nbody\n%%EOF",
            online_resume_filename="候选人_销售管培生.pdf",
        )
    )

    result = state["decision"]["result"]
    assert result["downloaded"] is True
    assert result["resumeReceived"] is True
    assert result["sourceKind"] == "online_resume"
    assert page.resume_requests == 0


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


def test_job51_online_resume_prefers_trusted_message_card_click() -> None:
    """When the top-right DOM click does not open preview, use the chat card entry."""

    position = "\u9500\u552e\u7ba1\u57f9\u751f"
    page = OnlineResumeEntryPage(
        conversations=[
            conversation(
                position,
                [
                    {"sender": "me", "text": "\u4f60\u662f\u5426\u63a5\u53d7\u51fa\u5dee\uff1f"},
                    {"sender": "other", "text": "\u53ef\u4ee5\u63a5\u53d7"},
                ],
                online_resume_download_bytes=b"%PDF-1.7\nbody\n%%EOF",
                online_resume_filename="candidate.pdf",
            )
        ],
        top_right_dom_click_opens=False,
        message_card_available=True,
    )
    adapter = Job51Adapter(page, owner="\u548c\u65b0\u7ea2")
    runner = ConversationRunner(adapter, rules=sample_rules())

    state = asyncio.run(runner.run_current())

    result = state["decision"]["result"]
    assert result["downloaded"] is True
    assert result["resumeReceived"] is True
    assert page.message_card_clicks == 1
    assert page.top_right_clicks == 0


def test_job51_online_resume_falls_back_to_trusted_top_right_click() -> None:
    """If the message card entry is absent, the top-right entry can open preview."""

    position = "\u9500\u552e\u7ba1\u57f9\u751f"
    page = OnlineResumeEntryPage(
        conversations=[
            conversation(
                position,
                [
                    {"sender": "me", "text": "\u4f60\u662f\u5426\u63a5\u53d7\u51fa\u5dee\uff1f"},
                    {"sender": "other", "text": "\u53ef\u4ee5\u63a5\u53d7"},
                ],
                online_resume_download_bytes=b"%PDF-1.7\nbody\n%%EOF",
                online_resume_filename="candidate.pdf",
            )
        ],
        top_right_dom_click_opens=False,
        message_card_available=False,
        top_right_trusted_click_opens=True,
    )

    opened = asyncio.run(_open_online_resume_preview(page))  # type: ignore[arg-type]

    assert opened["clicked"] is True
    assert opened["verified"] is True
    assert opened["source"] == "top_right_online_resume_trusted"
    assert page.top_right_clicks == 1


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


class RightHeaderIdentityPage:
    """Simulates 51job where the current identity is only reliable in the right header."""

    def __init__(
        self,
        *,
        right_header: dict[str, object],
        fallback_context: dict[str, object],
    ) -> None:
        self.right_header = right_header
        self.fallback_context = fallback_context
        self.right_header_reads = 0
        self.fallback_reads = 0

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        _ = arg
        right_header_script = getattr(
            job51_dom_scripts,
            "OPENED_CANDIDATE_STATE_JS",
            object(),
        )
        if script == "job51.opened_candidate_state":
            return {}
        if script == right_header_script:
            self.right_header_reads += 1
            return self.right_header
        if script in {"job51.read_chat_context", READ_CHAT_CONTEXT_JS}:
            self.fallback_reads += 1
            return self.fallback_context
        return {}


class TalentRadarRightHeaderPage:
    """Simulates the live 51job header shape with 人才罗盘 before 刚刚活跃."""

    header_text = "\n".join(
        [
            "姚亚回",
            "男 | 29岁 | 6年 | 本科 | 杭州（通勤距离14.5公里）",
            "|",
            "人才罗盘",
            "刚刚活跃",
            "在线简历",
            "沟通职位：",
            "投资交易策略研究员（量化与市场情绪方向）",
        ]
    )

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        expected = arg if isinstance(arg, dict) else {}
        if script == "job51.opened_candidate_state":
            return {}
        if script == job51_dom_scripts.OPENED_CANDIDATE_STATE_JS:
            actual_name = "姚亚回" if "ignoredHeaderNameLine" in script else "人才罗盘"
            opened = actual_name == expected.get("name")
            return {
                "opened": opened,
                "reason": "" if opened else "candidate_identity_mismatch",
                "chatReady": True,
                "source": "right_header",
                "expected": expected,
                "actual": {
                    "name": actual_name,
                    "position": "投资交易策略研究员（量化与市场情绪方向）",
                    "label": self.header_text,
                    "source": "right_header",
                    "headerText": self.header_text,
                },
            }
        return {}


class Job51RowsWithoutIdentityAttrsPage:
    """Real 51job list items do not carry name/position attrs on the row element."""

    is_fake = True

    def __init__(self, *, label: str, name: str, position: str) -> None:
        self.label = label
        self.name = name
        self.position = position
        self.row_clicked = False
        self.last_expected: dict[str, object] = {}
        self.reliable_actions: list[dict[str, object]] = []

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if script == "job51.read_unread_rows":
            return {
                "rows": [
                    {
                        "index": 0,
                        "id": "",
                        "label": self.label,
                        "name": self.name,
                        "position": self.position,
                        "unreadCount": 3,
                    }
                ]
            }
        if script == "job51.opened_candidate_state":
            return {}
        if script == job51_dom_scripts.OPENED_CANDIDATE_STATE_JS:
            expected = arg if isinstance(arg, dict) else {}
            self.last_expected = dict(expected)
            opened = bool(
                self.row_clicked
                and expected.get("name") == self.name
                and expected.get("position") == self.position
            )
            return {
                "opened": opened,
                "reason": "" if opened else "candidate_identity_mismatch",
                "chatReady": True,
                "source": "right_header",
                "expected": expected,
                "actual": {
                    "name": self.name if self.row_clicked else "",
                    "position": self.position if self.row_clicked else "",
                    "label": self.label if self.row_clicked else "",
                    "source": "right_header",
                },
            }
        if "thread_row_not_found" in script and "#conversation-list .list-item" in script:
            return {"clicked": False, "reason": "dom_click_not_used"}
        return {}

    async def query_all(self, selector: str) -> list[Job51RowWithoutIdentityAttrs]:
        if "#conversation-list .list-item" in selector:
            return [Job51RowWithoutIdentityAttrs(self)]
        return []

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> bool:
        _ = timeout_ms
        return selector == "#drop-area.input-textarea_self"


class Job51RowWithoutIdentityAttrs:
    def __init__(self, page: Job51RowsWithoutIdentityAttrsPage) -> None:
        self.page = page

    async def click(self, timeout_ms: int | None = None) -> None:
        _ = timeout_ms
        self.page.row_clicked = True

    async def text(self) -> str:
        return self.page.label

    async def attr(self, name: str) -> str | None:
        _ = name
        return None


class RightHeaderChatContextPage:
    """Simulates the current DOM script contract for 51job chat context."""

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
            if (
                "rightHeader" not in script
                or "沟通职位" not in script
                or "ignoredHeaderNameLine" not in script
                or "readHeaderName" not in script
            ):
                return {
                    "id": "沟通职位：外部财务产品顾问\n求职意向\n上海\n鲍女士\n1小时前活跃",
                    "label": "沟通职位：外部财务产品顾问\n求职意向\n上海\n鲍女士\n1小时前活跃",
                    "name": "上海",
                    "position": "外部财务产品顾问",
                    "messages": [],
                    "latest_message": "",
                    "unread_count": 1,
                }
            return {
                "id": "鲍女士 外部财务产品顾问",
                "label": "鲍女士 外部财务产品顾问",
                "name": "鲍女士",
                "position": "外部财务产品顾问",
                "messages": [],
                "latest_message": "",
                "unread_count": 1,
                "source": "right_header",
            }
        return {}


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
        self.guarded_identity_clicks = 0
        self.guarded_dom_clicks = 0

    async def handle_element_click(self, element):  # type: ignore[no-untyped-def]
        if element.selector.startswith("conversation:"):
            self.native_row_clicks += 1
        await super().handle_element_click(element)

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if script == "job51.click_thread_by_identity":
            result = await super().eval_js(script, arg)
            if isinstance(result, dict) and result.get("clicked"):
                self.guarded_identity_clicks += 1
            return result
        if "thread_row_not_found" in script and "#conversation-list .list-item" in script:
            if not self.app_download_blocker_installed:
                self.app_download_popups += 1
            payload = arg if isinstance(arg, dict) else {}
            self.selected_index = int(payload.get("index") or 0)
            self.guarded_dom_clicks += 1
            return {"clicked": True, "source": "fake_guarded_dom_click"}
        return await super().eval_js(script, arg)


class StubbornResumeOverlayPage:
    """Simulates a resume preview that remains visible after cleanup attempts."""

    async def query_all(self, selector: str):  # type: ignore[no-untyped-def]
        _ = selector
        return []

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        _ = arg
        if script == actions_resume_close.OVERLAY_STATE_JS:
            return {"remaining": ["online_resume_preview"]}
        return {"closed": False, "reason": "close_not_found"}

    async def press(self, selector: str, key: str, timeout_ms: int = 1000) -> bool:
        _ = selector, key, timeout_ms
        return True


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


class TopRightAttachmentPage:
    """Simulates a page where only the header annex entry opens the preview."""

    def __init__(self) -> None:
        self.top_right_clicked = False

    async def query_all(self, selector: str) -> list[InterceptedAttachmentElement]:
        _ = selector
        return []

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        _ = arg
        if script == "job51.click_attachment_resume":
            return {"clicked": False, "reason": "message_card_not_found"}
        if "file-style.annex" in script:
            self.top_right_clicked = True
            return {"clicked": True, "source": "top_right_attachment"}
        if "annex-resume" in script:
            return {
                "found": self.top_right_clicked,
                "href": "blob:resume" if self.top_right_clicked else "",
            }
        return {}


class LegacyAttachmentClickNotVerifiedPage(TopRightAttachmentPage):
    """Simulates a stale page helper that reports clicked without opening preview."""

    def __init__(self) -> None:
        super().__init__()
        self.legacy_clicked = False

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if script == "job51.click_attachment_resume":
            self.legacy_clicked = True
            return {"clicked": True, "source": "legacy_message_card"}
        return await super().eval_js(script, arg)


class OnlineResumeEntryPage(FakePage):
    def __init__(
        self,
        *args: object,
        top_right_dom_click_opens: bool = True,
        message_card_available: bool = True,
        top_right_trusted_click_opens: bool = True,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.top_right_dom_click_opens = top_right_dom_click_opens
        self.message_card_available = message_card_available
        self.top_right_trusted_click_opens = top_right_trusted_click_opens
        self.message_card_clicks = 0
        self.top_right_clicks = 0

    async def query_all(self, selector: str):  # type: ignore[no-untyped-def]
        if ".im-message-item .resume-element .info-content-item" in selector:
            return (
                [OnlineResumeEntryElement(self, "message_card_online_resume")]
                if self.message_card_available
                else []
            )
        if "#sensor_Bchat_newzxjl" in selector or ".chat-user-operate" in selector:
            return [OnlineResumeEntryElement(self, "top_right_online_resume")]
        if selector in {"#sensor_imresume_download", "#IMResumePrint"}:
            return (
                [OnlineResumeEntryElement(self, "online_resume_preview")]
                if self.current_conversation().get("online_resume_opened")
                else []
            )
        return await super().query_all(selector)

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if script == "job51.click_online_resume":
            found = bool(
                self.current_conversation().get("online_resume_download_bytes")
                or self.current_conversation().get("online_resume_bytes")
                or self.current_conversation().get("online_resume_href")
            )
            if found and self.top_right_dom_click_opens:
                self.current_conversation()["online_resume_opened"] = True
            return {
                "clicked": found,
                "label": "在线简历" if found else "",
                "source": "fake_top_right_dom_click",
                "reason": "" if found else "online_resume_button_not_found",
            }
        return await super().eval_js(script, arg)

    async def handle_online_resume_click(self, source: str) -> None:
        if source == "message_card_online_resume":
            self.message_card_clicks += 1
            self.current_conversation()["online_resume_opened"] = True
            return
        if source == "top_right_online_resume":
            self.top_right_clicks += 1
            if self.top_right_trusted_click_opens:
                self.current_conversation()["online_resume_opened"] = True


class OnlineResumeEntryElement:
    def __init__(self, page: OnlineResumeEntryPage, source: str) -> None:
        self.page = page
        self.source = source

    async def click(self, timeout_ms: int | None = None) -> None:
        _ = timeout_ms
        await self.page.handle_online_resume_click(self.source)

    async def text(self) -> str:
        return "在线简历"

    async def attr(self, name: str) -> str | None:
        _ = name
        return None


class AlwaysMismatchedJob51Page(FakePage):
    def __init__(self) -> None:
        super().__init__(
            conversations=[
                {
                    "id": "wrong-row",
                    "name": "错误候选人",
                    "position": "国际业务管培生",
                    "label": "错误候选人 国际业务管培生",
                    "latest_message": "你好",
                    "unread_count": 1,
                    "messages": [{"sender": "other", "text": "你好"}],
                }
            ]
        )
        self.identity_click_attempts = 0

    def _fake_unread_rows(self) -> list[dict[str, object]]:
        return [
            {
                "index": 0,
                "id": "target-row",
                "label": "目标候选人\nB端社交媒体运营\n简历已发送",
                "name": "目标候选人",
                "position": "B端社交媒体运营",
                "latestMessage": "简历已发送",
                "unreadCount": 1,
            }
        ]

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if script == "job51.click_thread_by_identity":
            self.identity_click_attempts += 1
            return {"clicked": True, "source": "fake_identity_click"}
        return await super().eval_js(script, arg)


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


def minimal_pdf_with_text(text: str) -> bytes:
    import fitz  # type: ignore[import-not-found]

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    return document.tobytes()


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
            "投资交易策略研究员（量化与市场情绪方向）": {
                "category": "investment_direct_resume",
                "directResume": True,
                "resumeJobType": "投资交易策略研究员",
                "resumeRequestPrompt": "你好，方便发一份简历过来吗",
                "aliases": ["投资交易策略研究员", "量化与市场情绪方向"],
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
        },
        "companyKnowledgeBase": {},
    }
