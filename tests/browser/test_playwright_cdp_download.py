"""Regression tests for real Playwright-CDP download helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.browser import playwright_cdp
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
    """A same-tab PDF navigation is readable, but the original page must stay open."""

    original = _ZhilianRawPage(opened_page=None)

    def navigate_same_page() -> None:
        original.url = "https://rd6.zhaopin.com/resume/attachment.pdf"

    original.on_click = navigate_same_page
    page = _FetchingCDPPage(original)

    result = asyncio.run(page._click_zhilian_attachment_resume_download(timeout_ms=15000))

    assert result["ok"] is True
    assert page.fetched_from is original
    assert original.closed is False


def test_zhilian_attachment_download_uses_popup_when_entry_click_times_out() -> None:
    opened = _RawPage()
    original = _ZhilianRawPage(opened_page=opened, click_should_timeout=True)
    page = _FetchingCDPPage(original)

    result = asyncio.run(page._click_zhilian_attachment_resume_download(timeout_ms=15000))

    assert result["ok"] is True
    assert result["source"] == "opened_pdf_url"
    assert result["clicked"]["openedPage"] is True
    assert "entry click timed out" in result["clicked"]["clickError"]
    assert opened.closed is True


def test_zhilian_attachment_download_prefers_toolbar_anchor_over_generic_text() -> None:
    opened = _RawPage()
    original = _ZhilianRawPage(opened_page=opened)
    page = _FetchingCDPPage(original)

    result = asyncio.run(page._click_zhilian_attachment_resume_download(timeout_ms=15000))

    assert result["ok"] is True
    assert original.locator_requests[0] == ".session-new-action a.km-button"
    assert result["clicked"]["entrySource"] == "toolbar_anchor"


def test_zhilian_attachment_download_does_not_fetch_unchanged_chat_page(
    tmp_path: Path,
) -> None:
    """Without popup or navigation, wait for the delayed download instead of reading HTML."""

    artifact_dir = tmp_path / "playwright-artifacts"
    artifact_dir.mkdir()
    download_file = artifact_dir / "same-page-direct.docx"
    download_file.write_bytes(b"PK\x03\x04direct-docx")
    original = _DelayedZhilianRawPage(
        opened_page=None,
        download=_Download(path=str(download_file), suggested_filename="same-page-direct.docx"),
        download_delay=0.05,
    )
    page = _FetchingCDPPage(original)

    result = asyncio.run(page._click_zhilian_attachment_resume_download(timeout_ms=500))

    assert result["ok"] is True
    assert result["source"] == "direct_attachment_download"
    assert result["bytes"] == b"PK\x03\x04direct-docx"
    assert page.fetched_from is None


def test_zhilian_attachment_download_captures_direct_download_when_popup_closes(
    tmp_path: Path,
) -> None:
    """A transient popup may close after handing the attachment to Chromium download."""

    download_file = tmp_path / "direct-resume.pdf"
    download_file.write_bytes(b"%PDF-1.7\ndirect\n%%EOF")
    popup = _AutoClosingRawPage()
    original = _ZhilianRawPage(
        opened_page=popup,
        download=_Download(path=str(download_file), suggested_filename="direct-resume.pdf"),
    )
    page = _ZhilianUUIDDownloadPage(original, tmp_path)

    result = asyncio.run(page._click_zhilian_attachment_resume_download(timeout_ms=15000))

    assert result["ok"] is True
    assert result["source"] == "direct_attachment_download"
    assert result["bytes"] == b"%PDF-1.7\ndirect\n%%EOF"
    assert popup.wait_timeout_calls == 0
    assert original.closed is False


def test_zhilian_attachment_download_waits_for_delayed_direct_download(
    tmp_path: Path,
) -> None:
    """The download event may arrive shortly after the transient popup closes."""

    artifact_dir = tmp_path / "playwright-artifacts"
    artifact_dir.mkdir()
    download_file = artifact_dir / "delayed-resume.pdf"
    download_file.write_bytes(b"%PDF-1.7\ndelayed\n%%EOF")
    popup = _AutoClosingRawPage()
    original = _DelayedZhilianRawPage(
        opened_page=popup,
        download=_Download(path=str(download_file), suggested_filename="delayed-resume.pdf"),
        download_delay=0.05,
    )
    page = _ZhilianUUIDDownloadPage(original, tmp_path)

    result = asyncio.run(page._click_zhilian_attachment_resume_download(timeout_ms=500))

    assert result["ok"] is True
    assert result["source"] == "direct_attachment_download"
    assert result["bytes"] == b"%PDF-1.7\ndelayed\n%%EOF"


def test_zhilian_attachment_download_reads_uuid_file_when_popup_closes(
    tmp_path: Path,
) -> None:
    """CDP download behavior preserves a file even when no Playwright event survives."""

    popup = _AutoClosingRawPage()
    uuid_file = tmp_path / "6b1e4e6c-attachment"

    def write_uuid_file() -> None:
        uuid_file.write_bytes(b"%PDF-1.7\nuuid\n%%EOF")

    original = _ZhilianRawPage(opened_page=popup, on_click=write_uuid_file)
    page = _ZhilianUUIDDownloadPage(original, tmp_path)

    result = asyncio.run(page._click_zhilian_attachment_resume_download(timeout_ms=15000))

    assert result["ok"] is True
    assert result["source"] == "zhilian_uuid_download"
    assert result["bytes"] == b"%PDF-1.7\nuuid\n%%EOF"
    assert popup.wait_timeout_calls == 0


def test_zhilian_attachment_download_reports_popup_closed_before_capture(
    tmp_path: Path,
) -> None:
    """A closed popup without any captured file gets a specific diagnostic reason."""

    popup = _AutoClosingRawPage()
    original = _ZhilianRawPage(opened_page=popup)
    page = _ZhilianUUIDDownloadPage(original, tmp_path)

    result = asyncio.run(page._click_zhilian_attachment_resume_download(timeout_ms=200))

    assert result["ok"] is False
    assert result["reason"] == "popup_closed_before_capture"
    assert result["clicked"]["popupClosedBeforeCapture"] is True
    assert popup.wait_timeout_calls == 0


def test_zhilian_attachment_download_fetches_trusted_temporary_popup_url(
    tmp_path: Path,
) -> None:
    popup = _AutoClosingRawPage()
    popup.url = (
        "https://attachment.zhaopin.com/resumeapi/parsev2/downloadFileTemporary"
        "?file=trusted-token&fileName=resume.pdf"
    )
    original = _ZhilianRawPage(opened_page=popup)
    request = _ContextRequest(b"%PDF-1.7\ncontext-fetch\n%%EOF")
    original.context.request = request
    page = _ZhilianUUIDDownloadPage(original, tmp_path)

    result = asyncio.run(page._click_zhilian_attachment_resume_download(timeout_ms=200))

    assert result["ok"] is True
    assert result["source"] == "zhilian_popup_url_fetch"
    assert result["bytes"] == b"%PDF-1.7\ncontext-fetch\n%%EOF"
    assert request.urls == [popup.url]


def test_zhilian_download_sets_uuid_download_behavior(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Zhilian direct downloads are routed into an isolated UUID directory."""

    monkeypatch.setattr(playwright_cdp, "PROJECT_ROOT", tmp_path)
    raw = _Job51DownloadRawPage(cdp_should_fail=False)
    page = PlaywrightCDPPage(raw)

    result = asyncio.run(page._setup_zhilian_uuid_download_behavior())

    assert result["ok"] is True
    command, params = raw.context.cdp_session.commands[0]
    assert command == "Browser.setDownloadBehavior"
    assert params["behavior"] == "allowAndName"
    assert params["eventsEnabled"] is True
    assert str(params["downloadPath"]).replace("\\", "/").endswith(
        "data/downloads/_browser_uuid/zhilian"
    )


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


def test_job51_download_uses_trusted_toolbar_save_when_legacy_id_is_missing(
    tmp_path: Path,
) -> None:
    download_file = tmp_path / "resume.pdf"
    download_file.write_bytes(b"%PDF-1.7\nbody\n%%EOF")
    raw = _Job51DownloadRawPage(
        cdp_should_fail=False,
        download=_Download(path=str(download_file), suggested_filename="resume.pdf"),
        save_visible=False,
        toolbar_save_visible=True,
    )
    page = _Job51UUIDDownloadPage(raw, tmp_path)

    result = asyncio.run(page._click_job51_online_resume_download(timeout_ms=15000))

    assert result["ok"] is True
    assert result["bytes"] == b"%PDF-1.7\nbody\n%%EOF"
    assert result["clicked"]["source"] == "job51_toolbar_semantic_save"
    assert raw.save_clicks == 0
    assert raw.toolbar_save_clicks == 1
    assert raw.confirm_clicks == 1


def test_job51_download_rejects_positional_toolbar_guess_without_clicking(
    tmp_path: Path,
) -> None:
    raw = _Job51DownloadRawPage(
        cdp_should_fail=False,
        download=None,
        save_visible=False,
        toolbar_save_visible=True,
        toolbar_target={
            "found": True,
            "trusted": False,
            "x": 1396,
            "y": 176,
            "source": "job51_toolbar_save_left_of_print",
            "label": "转发 ibtn",
        },
    )
    page = _Job51UUIDDownloadPage(raw, tmp_path)

    result = asyncio.run(page._click_job51_online_resume_download(timeout_ms=15000))

    assert result["ok"] is False
    assert result["reason"] == "online_resume_save_target_untrusted"
    assert raw.toolbar_save_clicks == 0
    assert raw.confirm_clicks == 0
    assert raw.expect_download_calls == 0


def test_job51_download_accepts_trusted_save_before_named_toolbar_cluster(
    tmp_path: Path,
) -> None:
    download_file = tmp_path / "resume.pdf"
    download_file.write_bytes(b"%PDF-1.7\nbody\n%%EOF")
    raw = _Job51DownloadRawPage(
        cdp_should_fail=False,
        download=_Download(path=str(download_file), suggested_filename="resume.pdf"),
        save_visible=False,
        toolbar_save_visible=True,
        toolbar_target={
            "found": True,
            "trusted": True,
            "x": 1054,
            "y": 20,
            "source": "job51_toolbar_save_before_named_cluster",
            "label": "ibtn",
            "selector": "[data-codex-job51-save-target='trusted']",
        },
    )
    page = _Job51UUIDDownloadPage(raw, tmp_path)

    result = asyncio.run(page._click_job51_online_resume_download(timeout_ms=15000))

    assert result["ok"] is True
    assert result["clicked"]["source"] == "job51_toolbar_save_before_named_cluster"
    assert raw.toolbar_save_clicks == 1
    assert raw.confirm_clicks == 1


def test_job51_save_target_recognizes_named_toolbar_cluster() -> None:
    script = playwright_cdp.JOB51_ONLINE_RESUME_SAVE_TARGET_JS

    assert "job51_toolbar_save_before_named_cluster" in script
    assert "收藏" in script
    assert "转发" in script
    assert "打印" in script


def test_job51_download_remeasures_trusted_toolbar_target_after_hover_shift(
    tmp_path: Path,
) -> None:
    download_file = tmp_path / "resume.pdf"
    download_file.write_bytes(b"%PDF-1.7\nbody\n%%EOF")
    raw = _Job51DownloadRawPage(
        cdp_should_fail=False,
        download=_Download(path=str(download_file), suggested_filename="resume.pdf"),
        save_visible=False,
        toolbar_save_visible=True,
        toolbar_boxes=[
            {"x": 1380, "y": 160, "width": 24, "height": 24},
            {"x": 1280, "y": 180, "width": 24, "height": 24},
        ],
    )
    page = _Job51UUIDDownloadPage(raw, tmp_path)

    result = asyncio.run(page._click_job51_online_resume_download(timeout_ms=15000))

    assert result["ok"] is True
    assert raw.clicked_coordinates == [(1292.0, 192.0)]
    assert raw.toolbar_box_reads == 2


def test_job51_download_waits_for_save_dialog_with_bounded_timeout(
    tmp_path: Path,
) -> None:
    download_file = tmp_path / "resume.pdf"
    download_file.write_bytes(b"%PDF-1.7\nbody\n%%EOF")
    raw = _Job51DownloadRawPage(
        cdp_should_fail=False,
        download=_Download(path=str(download_file), suggested_filename="resume.pdf"),
    )
    page = _Job51UUIDDownloadPage(raw, tmp_path)

    result = asyncio.run(page._click_job51_online_resume_download(timeout_ms=15000))

    assert result["ok"] is True
    assert raw.dialog_wait_timeouts == [4000]


def test_job51_download_continues_when_pdf_button_is_not_stable(tmp_path: Path) -> None:
    download_file = tmp_path / "resume.pdf"
    download_file.write_bytes(b"%PDF-1.7\nbody\n%%EOF")
    raw = _Job51DownloadRawPage(
        cdp_should_fail=False,
        download=_Download(path=str(download_file), suggested_filename="resume.pdf"),
        pdf_click_should_timeout=True,
    )
    page = _Job51UUIDDownloadPage(raw, tmp_path)

    result = asyncio.run(page._click_job51_online_resume_download(timeout_ms=15000))

    assert result["ok"] is True
    assert result["bytes"] == b"%PDF-1.7\nbody\n%%EOF"
    assert raw.save_clicks == 1
    assert raw.pdf_clicks == 1
    assert raw.confirm_clicks == 1


def test_job51_download_stops_before_waiting_when_export_button_is_not_visible(
    tmp_path: Path,
) -> None:
    raw = _Job51DownloadRawPage(
        cdp_should_fail=False,
        download=None,
        save_visible=False,
    )
    page = _Job51UUIDDownloadPage(raw, tmp_path)

    result = asyncio.run(page._click_job51_online_resume_download(timeout_ms=15000))

    assert result["ok"] is False
    assert result["reason"] == "online_resume_export_not_available"
    assert raw.save_clicks == 0
    assert raw.expect_download_calls == 0


def test_job51_download_targets_only_visible_save_dialog(tmp_path: Path) -> None:
    download_file = tmp_path / "resume.pdf"
    download_file.write_bytes(b"%PDF-1.7\nbody\n%%EOF")
    raw = _Job51DownloadRawPage(
        cdp_should_fail=False,
        download=_Download(path=str(download_file), suggested_filename="resume.pdf"),
    )
    page = _Job51UUIDDownloadPage(raw, tmp_path)

    result = asyncio.run(page._click_job51_online_resume_download(timeout_ms=15000))

    assert result["ok"] is True
    assert ".el-dialog:visible" in raw.locator_requests
    assert raw.confirm_clicks == 1


def test_job51_download_reports_async_export_without_immediate_file(tmp_path: Path) -> None:
    """51 may queue an export and show a success dialog without a download event."""

    raw = _Job51DownloadRawPage(
        cdp_should_fail=False,
        download=None,
        export_status_visible=True,
    )
    page = _Job51UUIDDownloadPage(raw, tmp_path)

    result = asyncio.run(page._click_job51_online_resume_download(timeout_ms=200))

    assert result["ok"] is False
    assert result["reason"] == "online_resume_export_queued_no_file"
    assert result["exportQueued"] is True
    assert result["clicked"]["confirmed"] is True
    assert raw.confirm_clicks == 1


class _FetchingCDPPage(PlaywrightCDPPage):
    def __init__(self, page: Any) -> None:
        super().__init__(page)
        self.fetched_from: Any | None = None

    async def _fetch_current_page_bytes(self, page: Any) -> dict[str, Any]:
        self.fetched_from = page
        return {"ok": True, "bytes": b"%PDF-1.4", "filename": "resume.pdf"}

    async def _setup_zhilian_uuid_download_behavior(self) -> dict[str, Any]:
        return {"ok": False, "reason": "not_needed_for_stable_popup_test"}


class _RawPage:
    def __init__(self, opened_page: Any | None = None) -> None:
        self.context = _Context(opened_page)
        self.closed = False
        self.url = "https://rd6.zhaopin.com/app/im"

    def get_by_text(self, text: str) -> _Locator:
        _ = text
        return _Locator()

    def locator(self, selector: str) -> _Locator:
        _ = selector
        return _Locator()

    async def wait_for_load_state(self, state: str, timeout: int) -> None:
        _ = state, timeout

    async def wait_for_timeout(self, timeout: int) -> None:
        _ = timeout

    async def close(self) -> None:
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed


class _AutoClosingRawPage(_RawPage):
    def __init__(self) -> None:
        super().__init__()
        self.closed = True
        self.wait_timeout_calls = 0

    async def wait_for_load_state(self, state: str, timeout: int) -> None:
        _ = state, timeout
        raise RuntimeError("Target page, context or browser has been closed")

    async def wait_for_timeout(self, timeout: int) -> None:
        _ = timeout
        self.wait_timeout_calls += 1
        raise AssertionError("closed popup must not be awaited")


class _ZhilianUUIDDownloadPage(PlaywrightCDPPage):
    def __init__(self, page: Any, download_dir: Path) -> None:
        super().__init__(page)
        self.download_dir = download_dir

    async def _setup_zhilian_uuid_download_behavior(self) -> dict[str, Any]:
        return {"ok": True, "downloadPath": str(self.download_dir)}


class _ZhilianRawPage(_RawPage):
    def __init__(
        self,
        *,
        opened_page: Any | None,
        download: _Download | None = None,
        on_click: Any | None = None,
        click_should_timeout: bool = False,
    ) -> None:
        super().__init__(opened_page=opened_page)
        self.download = download
        self.on_click = on_click
        self.click_should_timeout = click_should_timeout
        self.view_clicks = 0
        self.locator_requests: list[str] = []

    def get_by_text(self, text: str) -> _ZhilianLocator:
        _ = text
        return _ZhilianLocator(self)

    def locator(self, selector: str) -> _ZhilianLocator:
        self.locator_requests.append(selector)
        return _ZhilianLocator(self, selector=selector)

    async def wait_for_event(self, event: str, timeout: int) -> Any:
        _ = timeout
        if event == "download" and self.download is not None:
            return self.download
        raise TimeoutError(f"no {event}")


class _DelayedZhilianRawPage(_ZhilianRawPage):
    def __init__(
        self,
        *,
        opened_page: Any | None,
        download: _Download,
        download_delay: float,
    ) -> None:
        super().__init__(opened_page=opened_page, download=download)
        self.download_delay = download_delay

    async def wait_for_event(self, event: str, timeout: int) -> Any:
        if event == "download":
            await asyncio.sleep(self.download_delay)
        return await super().wait_for_event(event, timeout)


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
        pdf_click_should_timeout: bool = False,
        save_visible: bool = True,
        toolbar_save_visible: bool = False,
        toolbar_target: dict[str, object] | None = None,
        toolbar_boxes: list[dict[str, float]] | None = None,
        dialog_visible: bool = True,
        export_status_visible: bool = False,
    ) -> None:
        self.context = _DownloadContext(cdp_should_fail=cdp_should_fail)
        self.save_clicks = 0
        self.pdf_clicks = 0
        self.confirm_clicks = 0
        self.pdf_click_should_timeout = pdf_click_should_timeout
        self.save_visible = save_visible
        self.toolbar_save_visible = toolbar_save_visible
        self.toolbar_target = toolbar_target
        self.toolbar_boxes = list(toolbar_boxes or [])
        self.toolbar_box_reads = 0
        self.toolbar_save_clicks = 0
        self.clicked_coordinates: list[tuple[float, float]] = []
        self.dialog_visible = dialog_visible
        self.dialog_wait_timeouts: list[int] = []
        self.export_status_visible = export_status_visible
        self.url = "https://ehire.51job.com/Revision/chat"
        self.download = download
        self.expect_download_calls = 0
        self.locator_requests: list[str] = []
        self.mouse = _Job51Mouse(self)

    def locator(self, selector: str) -> _Job51Locator:
        self.locator_requests.append(selector)
        return _Job51Locator(self, selector)

    async def evaluate(self, script: str, arg: object | None = None) -> dict[str, object]:
        _ = arg
        if "job51_online_resume_save_target" not in script:
            return {}
        if not self.toolbar_save_visible:
            return {"found": False, "reason": "online_resume_save_icon_not_found"}
        return dict(self.toolbar_target or {
            "found": True,
            "trusted": True,
            "x": 1396,
            "y": 176,
            "source": "job51_toolbar_semantic_save",
            "label": "保存 download",
            "selector": "[data-codex-job51-save-target='trusted']",
        })

    async def wait_for_timeout(self, timeout: int) -> None:
        _ = timeout

    def expect_download(self, timeout: int):  # noqa: ANN001
        _ = timeout
        self.expect_download_calls += 1
        if self.download is None and self.export_status_visible:
            return _TimedOutDownload()
        if self.download is None:
            raise AssertionError("download should not be awaited when CDP setup fails")
        return _ExpectDownload(self.download)


class _Job51Mouse:
    def __init__(self, page: _Job51DownloadRawPage) -> None:
        self.page = page

    async def move(self, x: float, y: float, *, steps: int = 1) -> None:
        _ = x, y, steps

    async def click(self, x: float, y: float) -> None:
        self.page.clicked_coordinates.append((x, y))
        self.page.toolbar_save_clicks += 1


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


class _TimedOutDownload:
    async def __aenter__(self) -> _TimedOutDownload:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        _ = exc_type, exc, tb
        raise TimeoutError("download event did not arrive")


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
    def __init__(
        self,
        page: _Job51DownloadRawPage,
        selector: str,
        *,
        has_text: str = "",
    ) -> None:
        self.page = page
        self.selector = selector
        self.has_text = has_text

    @property
    def first(self) -> _Job51Locator:
        return self

    @property
    def last(self) -> _Job51Locator:
        return self

    def filter(self, *, has_text: str) -> _Job51Locator:
        return _Job51Locator(self.page, self.selector, has_text=has_text)

    def locator(self, selector: str) -> _Job51Locator:
        return _Job51Locator(self.page, selector, has_text=self.has_text)

    async def count(self) -> int:
        if self.selector == "#sensor_imresume_download" and not self.page.save_visible:
            return 0
        if "el-message-box" in self.selector:
            return int(self.page.export_status_visible)
        return 1

    async def is_visible(self) -> bool:
        if self.selector == "#sensor_imresume_download":
            return self.page.save_visible
        if self.selector == ".el-dialog:visible":
            return self.page.dialog_visible
        if "el-message-box" in self.selector:
            return self.page.export_status_visible
        return True

    async def wait_for(self, *, state: str, timeout: int) -> None:
        _ = state
        if self.selector == ".el-dialog:visible":
            self.page.dialog_wait_timeouts.append(timeout)
            if not self.page.dialog_visible:
                raise TimeoutError("save dialog did not become visible")

    async def bounding_box(self, timeout: int) -> dict[str, float] | None:
        _ = timeout
        if "data-codex-job51-save-target" not in self.selector:
            return None
        boxes = self.page.toolbar_boxes or [
            {"x": 1384, "y": 164, "width": 24, "height": 24}
        ]
        index = min(self.page.toolbar_box_reads, len(boxes) - 1)
        self.page.toolbar_box_reads += 1
        return dict(boxes[index])

    async def click(self, timeout: int) -> None:
        _ = timeout
        if self.selector == "#sensor_imresume_download":
            self.page.save_clicks += 1
        elif self.has_text == "Pdf":
            self.page.pdf_clicks += 1
            if self.page.pdf_click_should_timeout:
                raise TimeoutError("Pdf button is already active but not stable")
        elif self.has_text == "确定":
            self.page.confirm_clicks += 1

    async def inner_text(self, timeout: int) -> str:
        _ = timeout
        if "el-message-box" in self.selector and self.page.export_status_visible:
            return "导出成功后会在当前页面展示下载结果，可在个人中心 - 导出记录中查看"
        return ""


class _Context:
    def __init__(self, opened_page: Any | None) -> None:
        self.opened_page = opened_page

    async def wait_for_event(self, event: str, timeout: int) -> Any:
        _ = timeout
        if event != "page" or self.opened_page is None:
            raise TimeoutError("no popup")
        return self.opened_page


class _ContextRequest:
    def __init__(self, body: bytes) -> None:
        self.body_bytes = body
        self.urls: list[str] = []

    async def get(self, url: str, *, timeout: int) -> _ContextResponse:
        _ = timeout
        self.urls.append(url)
        return _ContextResponse(self.body_bytes)


class _ContextResponse:
    ok = True
    status = 200
    headers = {
        "content-type": "application/pdf",
        "content-disposition": 'attachment; filename="resume.pdf"',
    }

    def __init__(self, body: bytes) -> None:
        self.body_bytes = body

    async def body(self) -> bytes:
        return self.body_bytes


class _Locator:
    @property
    def last(self) -> _Locator:
        return self

    def filter(self, *, has_text: str) -> _Locator:
        _ = has_text
        return self

    async def count(self) -> int:
        return 1

    async def click(self, timeout: int) -> None:
        _ = timeout


class _ZhilianLocator(_Locator):
    def __init__(self, page: _ZhilianRawPage, *, selector: str = "") -> None:
        self.page = page
        self.selector = selector

    @property
    def last(self) -> _ZhilianLocator:
        return self

    def filter(self, *, has_text: str) -> _ZhilianLocator:
        _ = has_text
        return self

    async def click(self, timeout: int) -> None:
        _ = timeout
        self.page.view_clicks += 1
        if callable(self.page.on_click):
            self.page.on_click()
        if self.page.click_should_timeout:
            raise TimeoutError("entry click timed out after popup opened")
