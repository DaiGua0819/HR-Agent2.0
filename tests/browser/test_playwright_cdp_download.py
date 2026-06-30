"""Regression tests for real Playwright-CDP download helpers."""

from __future__ import annotations

import asyncio
from typing import Any

from app.browser.playwright_cdp import PlaywrightCDPPage


def test_zhilian_attachment_download_closes_opened_page() -> None:
    """Zhilian opens a PDF tab for attachment resumes; close it after capture."""

    opened = _RawPage()
    original = _RawPage(opened_page=opened)
    page = _FetchingCDPPage(original)

    result = asyncio.run(page._click_zhilian_attachment_resume_download(timeout_ms=15000))

    assert result["ok"] is True
    assert page.fetched_from is opened
    assert opened.closed is True
    assert original.closed is False


def test_zhilian_attachment_download_does_not_close_original_page_without_popup() -> None:
    """If no new tab appears, the chat page is the target and must stay open."""

    original = _RawPage(opened_page=None)
    page = _FetchingCDPPage(original)

    result = asyncio.run(page._click_zhilian_attachment_resume_download(timeout_ms=15000))

    assert result["ok"] is True
    assert page.fetched_from is original
    assert original.closed is False


class _FetchingCDPPage(PlaywrightCDPPage):
    def __init__(self, page: Any) -> None:
        super().__init__(page)
        self.fetched_from: Any | None = None

    async def _fetch_current_page_bytes(self, page: Any) -> dict[str, Any]:
        self.fetched_from = page
        return {"ok": True, "bytes": b"%PDF-1.4", "filename": "resume.pdf"}


class _RawPage:
    def __init__(self, opened_page: Any | None = None) -> None:
        self.context = _Context(opened_page)
        self.closed = False
        self.url = "https://rd6.zhaopin.com/app/im"

    def get_by_text(self, text: str) -> _Locator:
        _ = text
        return _Locator()

    async def wait_for_load_state(self, state: str, timeout: int) -> None:
        _ = state, timeout

    async def wait_for_timeout(self, timeout: int) -> None:
        _ = timeout

    async def close(self) -> None:
        self.closed = True


class _Context:
    def __init__(self, opened_page: Any | None) -> None:
        self.opened_page = opened_page

    async def wait_for_event(self, event: str, timeout: int) -> Any:
        _ = timeout
        if event != "page" or self.opened_page is None:
            raise TimeoutError("no popup")
        return self.opened_page


class _Locator:
    @property
    def last(self) -> _Locator:
        return self

    async def count(self) -> int:
        return 1

    async def click(self, timeout: int) -> None:
        _ = timeout
