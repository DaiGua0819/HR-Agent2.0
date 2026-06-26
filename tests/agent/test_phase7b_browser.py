"""Phase 7b：真实浏览器接口后的 dry-run 与选择器验证测试。

测试仍全部使用 FakePage / fake CDP 连接，不依赖真实 CloakBrowser 或登录态。
"""

from __future__ import annotations

import asyncio
import json

from app.browser.fake_page import FakePage
from app.browser.manager import BrowserManager
from app.browser.read_once import dry_run_read_once
from app.browser.selector_validation import detect_login_page, validate_platform_selectors
from app.core.constants import Platform
from app.evaluation.decision_log import InMemoryDecisionSink


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


def test_real_browser_manager_can_be_mocked_without_cdp(monkeypatch) -> None:
    """real 后端通过 CDP 连接工厂装配三平台页面，单测不连真实浏览器。"""

    urls: list[str] = []

    async def ready(_url: str, *, timeout_seconds: float = 5) -> bool:
        _ = timeout_seconds
        return True

    async def connect(url: str) -> FakeConnection:
        urls.append(url)
        return FakeConnection()

    monkeypatch.setattr("app.browser.lifecycle.ensure_cdp_ready", ready)
    monkeypatch.setattr("app.browser.playwright_cdp.connect_cdp_browser", connect)

    manager = BrowserManager(owner="和新红", cdp_port=9222, backend="real")
    asyncio.run(manager.start())

    assert urls == ["http://127.0.0.1:9222"]
    assert set(manager.pages) == {Platform.BOSS, Platform.JOB51, Platform.ZHILIAN}
    assert manager.pages[Platform.BOSS] is not manager.pages[Platform.ZHILIAN]


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

    async def ensure_page(
        self,
        *,
        name: str,
        url: str = "",
        url_hint: str = "",
    ) -> FakePage:
        _ = (name, url_hint)
        page = FakePage()
        if url:
            await page.goto(url)
        self.created.append(page)
        return page

    def is_connected(self) -> bool:
        return True


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
