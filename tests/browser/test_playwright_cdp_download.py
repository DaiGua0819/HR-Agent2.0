"""Regression tests for real Playwright-CDP download helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path
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


def test_job51_download_sets_uuid_download_behavior_before_clicking_save() -> None:
    raw = _Job51DownloadRawPage(cdp_should_fail=True)
    page = PlaywrightCDPPage(raw)

    result = asyncio.run(page._click_job51_online_resume_download(timeout_ms=15000))

    assert result["ok"] is False
    assert result["reason"] == "download_behavior_setup_failed"
    command, params = raw.context.cdp_session.commands[0]
    assert command == "Browser.setDownloadBehavior"
    assert params["behavior"] == "allowAndName"
    assert params["eventsEnabled"] is True
    assert str(params["downloadPath"]).replace("\\", "/").endswith(
        "data/downloads/_browser_uuid/job51"
    )
    assert raw.save_clicks == 0


def test_job51_download_reads_uuid_file_when_artifact_path_is_missing(tmp_path: Path) -> None:
    artifact_path = tmp_path / "playwright-artifacts" / "uuid-download"
    uuid_file = tmp_path / "uuid-download"
    uuid_file.write_bytes(b"%PDF-1.7\nbody\n%%EOF")
    raw = _Job51DownloadRawPage(
        cdp_should_fail=False,
        download=_Download(path=str(artifact_path), suggested_filename="resume.pdf"),
    )
    page = _Job51UUIDDownloadPage(raw, tmp_path)

    result = asyncio.run(page._click_job51_online_resume_download(timeout_ms=15000))

    assert result["ok"] is True
    assert result["bytes"] == b"%PDF-1.7\nbody\n%%EOF"
    assert result["path"] == str(uuid_file)
    assert raw.save_clicks == 1


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


class _Job51UUIDDownloadPage(PlaywrightCDPPage):
    def __init__(self, page: Any, download_dir: Path) -> None:
        super().__init__(page)
        self.download_dir = download_dir

    async def _setup_job51_uuid_download_behavior(self) -> dict[str, Any]:
        return {"ok": True, "downloadPath": str(self.download_dir)}


class _Job51DownloadRawPage:
    def __init__(
        self,
        *,
        cdp_should_fail: bool = False,
        download: _Download | None = None,
    ) -> None:
        self.context = _DownloadContext(cdp_should_fail=cdp_should_fail)
        self.save_clicks = 0
        self.url = "https://ehire.51job.com/Revision/chat"
        self.download = download

    def locator(self, selector: str) -> _Job51Locator:
        return _Job51Locator(self, selector)

    async def wait_for_timeout(self, timeout: int) -> None:
        _ = timeout

    def expect_download(self, timeout: int):  # noqa: ANN001
        _ = timeout
        if self.download is None:
            raise AssertionError("download should not be awaited when CDP setup fails")
        return _ExpectDownload(self.download)


class _ExpectDownload:
    def __init__(self, download: _Download) -> None:
        self.download = download

    async def __aenter__(self) -> _ExpectDownload:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        _ = exc_type, exc, tb

    @property
    async def value(self) -> _Download:
        return self.download


class _Download:
    def __init__(self, *, path: str | None, suggested_filename: str) -> None:
        self._path = path
        self.suggested_filename = suggested_filename

    async def path(self) -> str | None:
        return self._path

    async def save_as(self, target: str) -> None:
        Path(target).write_bytes(b"%PDF-1.7\nbody\n%%EOF")


class _DownloadContext:
    def __init__(self, *, cdp_should_fail: bool) -> None:
        self.cdp_session = _DownloadCDPSession(should_fail=cdp_should_fail)

    async def new_cdp_session(self, page: object) -> _DownloadCDPSession:
        _ = page
        return self.cdp_session


class _DownloadCDPSession:
    def __init__(self, *, should_fail: bool) -> None:
        self.should_fail = should_fail
        self.commands: list[tuple[str, dict[str, object]]] = []

    async def send(self, command: str, params: dict[str, object]) -> None:
        self.commands.append((command, dict(params)))
        if self.should_fail:
            raise RuntimeError("cdp refused download behavior")


class _Job51Locator:
    def __init__(self, page: _Job51DownloadRawPage, selector: str) -> None:
        self.page = page
        self.selector = selector

    @property
    def first(self) -> _Job51Locator:
        return self

    @property
    def last(self) -> _Job51Locator:
        return self

    def filter(self, *, has_text: str) -> _Job51Locator:
        _ = has_text
        return self

    def locator(self, selector: str) -> _Job51Locator:
        _ = selector
        return self

    async def count(self) -> int:
        return 1

    async def click(self, timeout: int) -> None:
        _ = timeout
        if self.selector == "#sensor_imresume_download":
            self.page.save_clicks += 1


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
