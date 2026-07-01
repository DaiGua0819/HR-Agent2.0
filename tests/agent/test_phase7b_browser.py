"""Phase 7b：真实浏览器接口后的 dry-run 与选择器验证测试。

测试仍全部使用 FakePage / fake CDP 连接，不依赖真实 CloakBrowser 或登录态。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
from pathlib import Path

import pytest
from app.browser.fake_page import FakePage
from app.browser.manager import BrowserManager
from app.browser.playwright_cdp import PlaywrightCDPConnection
from app.browser.read_once import dry_run_read_once
from app.browser.selector_validation import detect_login_page, validate_platform_selectors
from app.core.constants import Platform
from app.evaluation.decision_log import InMemoryDecisionSink
from app.platforms.zhilian import selectors as zhilian_selectors
from scripts.platform_once_common import _health_check, _print_summary


class TinyPage:
    def __init__(self, url: str, rows: int = 0) -> None:
        self.url = url
        self.rows = rows

    async def evaluate(self, script: str) -> int:
        _ = script
        return self.rows


class TinyContext:
    def __init__(self, pages: list[TinyPage]) -> None:
        self.pages = pages


def test_selector_validation_reports_statuses_on_fake_page() -> None:
    """选择器验证器只读查询页面并输出结构化状态。"""

    page = FakePage(conversations=[_conversation()])
    results = asyncio.run(validate_platform_selectors(page, Platform.BOSS))
    by_name = {item.name: item for item in results}

    assert by_name["会话列表"].status == "OK"
    assert by_name["推荐候选卡"].status == "缺失"
    assert "boss-recruiter-automation" in by_name["会话列表"].source
    json.dumps([item.__dict__ for item in results], ensure_ascii=False)


def test_login_detection_identifies_login_page_before_selector_validation() -> None:
    """未登录页面先被识别，不进入业务选择器验证。"""

    page = FakePage(url="https://login.zhipin.com/", body_text="扫码登录 密码登录")
    detection = asyncio.run(detect_login_page(page, Platform.BOSS))

    assert detection.logged_out is True
    assert detection.reason == "url_login_marker"


def test_job51_chat_page_is_not_misread_as_login() -> None:
    """51job 聊天页里可能有登录字样，不能被误判为登录页。"""

    page = FakePage(
        url="https://ehire.51job.com/Revision/chat?rt=1",
        body_text="人才沟通 全部职位 未读 开启微信通知 登录",
    )
    detection = asyncio.run(detect_login_page(page, Platform.JOB51))

    assert detection.logged_out is False


def test_cloak_browser_manager_can_be_mocked_without_cdp(monkeypatch) -> None:
    """cloak 后端通过 CDP 连接工厂装配三平台页面，单测不连真实浏览器。"""

    urls: list[str] = []
    connection = FakeConnection()

    async def ready(_url: str, *, timeout_seconds: float = 5) -> bool:
        _ = timeout_seconds
        return True
    async def connect(url: str) -> FakeConnection:
        urls.append(url)
        return connection

    monkeypatch.setattr("app.browser.lifecycle.ensure_cdp_ready", ready)
    monkeypatch.setattr("app.browser.playwright_cdp.connect_cdp_browser", connect)

    manager = BrowserManager(owner="和新红", cdp_port=9222, backend="cloak")
    asyncio.run(manager.start())

    assert urls == ["http://127.0.0.1:9222"]
    assert set(manager.pages) == {Platform.BOSS, Platform.JOB51, Platform.ZHILIAN}
    assert manager.pages[Platform.BOSS] is not manager.pages[Platform.ZHILIAN]
    job51_request = next(item for item in connection.requests if item["name"] == "job51")
    assert job51_request["url"] == "https://ehire.51job.com/Revision/chat"
    assert job51_request["url_hint"] == "ehire.51job.com/Revision/chat"
    zhilian_request = next(item for item in connection.requests if item["name"] == "zhilian")
    assert zhilian_request["url_hint"] == "rd6.zhaopin.com/app/im"


def test_per_platform_cloak_backend_is_rejected() -> None:
    """真实浏览器不再允许每平台一个 CDP 的旧拓扑。"""

    manager = BrowserManager(owner="和新红", cdp_port=9222, backend="cloak-per-platform")
    with pytest.raises(ValueError, match="fake/cloak"):
        asyncio.run(manager.start())


def test_cdp_page_lookup_prefers_latest_matching_tab() -> None:
    """多个同平台标签页并存时，优先复用最新的匹配页。"""

    old = TinyPage("https://ehire.51job.com/Revision/chat?rt=old")
    new = TinyPage("https://ehire.51job.com/Revision/chat?rt=new")
    connection = PlaywrightCDPConnection(
        playwright=None,
        browser=None,
        context=TinyContext([old, new]),
    )

    assert connection._find_page("ehire.51job.com/Revision/chat") is new


def test_cdp_job51_lookup_prefers_ready_chat_tab() -> None:
    """51job 多标签并存时，优先选已有会话列表的聊天页。"""

    ready = TinyPage("https://ehire.51job.com/Revision/chat?rt=ready", rows=8)
    blank = TinyPage("https://ehire.51job.com/Revision/chat?rt=blank", rows=0)
    connection = PlaywrightCDPConnection(
        playwright=None,
        browser=None,
        context=TinyContext([ready, blank]),
    )

    page = asyncio.run(connection._find_ready_page("ehire.51job.com/Revision/chat"))

    assert page is ready


def test_zhilian_preflight_does_not_require_chat_panel_before_opening_thread() -> None:
    """智联初始预检只硬性要求会话列表，聊天区在点开候选人后验证。"""

    page = SelectorCountPage(
        {
            zhilian_selectors.SESSION_ITEM: 3,
            zhilian_selectors.CHAT_READY: 0,
            zhilian_selectors.MESSAGE_ITEM: 0,
        }
    )
    adapter = PreflightAdapter(page)

    missing = asyncio.run(_health_check(Platform.ZHILIAN, adapter))

    assert missing == []


def test_boss_confirmed_live_allows_high_limit_for_full_unread_pass(monkeypatch) -> None:
    """用户确认 live 后，BOSS 单次处理不再限制 3/10 人。"""

    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts_dir))
    run_boss_once = importlib.import_module("run_boss_once")
    args = argparse.Namespace(live=True, confirm_live=True, owner="宋峰峰", limit=50)

    assert run_boss_once._resolve_mode(args) is True
    assert run_boss_once.os.environ["DRY_RUN"] == "false"


def test_platform_summary_print_handles_unencodable_console_text(monkeypatch) -> None:
    """Windows GBK consoles should not crash when a candidate message contains emoji."""

    stdout = StrictGbkStdout()
    monkeypatch.setattr(sys, "stdout", stdout)

    _print_summary(
        Platform.ZHILIAN,
        [
            {
                "conversationId": "conv-1",
                "sessionId": "session-1",
                "candidate": {"name": "候选人"},
                "job": "AI应用开发实习生",
                "lastMessage": {"sender": "other", "text": "可以🤝"},
                "action": "wait",
                "stage": "resume_already_requested",
                "ruleSource": "positionReplies",
                "sentMessages": [],
                "artifactWritten": False,
                "candidateStatusWritten": True,
                "decision": {"action": "wait", "reason": "resume_already_requested"},
            }
        ],
        live=True,
    )

    output = "".join(stdout.writes)
    assert "zhilian LIVE summary" in output
    assert "可以?" in output


def test_dry_run_read_once_records_intent_without_side_effect(monkeypatch) -> None:
    """dry-run 读路径会判断下一步，但不会真的写入 FakePage 消息。"""

    events: list[dict[str, object]] = []
    monkeypatch.setattr("app.core.dry_run.record_decision", lambda event: events.append(event))
    page = FakePage(conversations=[_conversation(position="企业内容运营负责人（B2B/短视频方向）")])
    manager = BrowserManager(
        owner="和新红",
        cdp_port=9222,
        backend="fake",
        pages={Platform.BOSS: page},
        started=True,
    )
    sink = InMemoryDecisionSink()

    result = asyncio.run(
        dry_run_read_once(
            manager,
            owner="和新红",
            platform=Platform.BOSS,
            decision_sink=sink,
        )
    )
    assert result["dryRun"] is True
    assert result["processed"] == 1
    assert events and events[0]["event"] == "dry_run_intent"
    assert page.sent_messages == []
    assert page.resume_requests == 0
    assert sink.events


class FakeConnection:
    """模拟 Playwright CDP 连接。"""

    def __init__(self) -> None:
        self.created: list[FakePage] = []
        self.requests: list[dict[str, str]] = []

    async def ensure_page(
        self,
        *,
        name: str,
        url: str = "",
        url_hint: str = "",
    ) -> FakePage:
        self.requests.append({"name": name, "url": url, "url_hint": url_hint})
        page = FakePage()
        if url:
            await page.goto(url)
        self.created.append(page)
        return page

    def is_connected(self) -> bool:
        return True


class PreflightAdapter:
    def __init__(self, page: SelectorCountPage) -> None:
        self.page = page

    async def select_positions(self, target_position: str | None = None) -> dict[str, object]:
        _ = target_position
        return {"selected": True}

    async def select_unread_filter(self) -> dict[str, object]:
        return {"selected": True}


class SelectorCountPage:
    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts

    async def query_all(self, selector: str) -> list[object]:
        return [object()] * self.counts.get(selector, 0)


class StrictGbkStdout:
    encoding = "gbk"
    errors = "strict"

    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, text: str) -> int:
        text.encode(self.encoding, errors=self.errors)
        self.writes.append(text)
        return len(text)

    def flush(self) -> None:
        return None


def _conversation(position: str = "销售管培生") -> dict[str, object]:
    return {
        "id": "phase7b-conv",
        "name": "候选人",
        "position": position,
        "label": f"候选人 {position}",
        "latest_message": "你好",
        "unread_count": 1,
        "messages": [{"sender": "other", "text": "你好"}],
    }
