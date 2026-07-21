"""Playwright CDP 页面实现。

真实浏览器被封装在 `BrowserPage` 接口后面：平台动作层只看 query/click/fill/text
等最小方法，测试仍可继续使用 FakePage。这里连接的是已经运行的 CloakBrowser CDP，
不会主动启动浏览器，也不会绕过 dry-run 执行业务副作用。
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir
from typing import Any
from urllib.parse import urlparse

from app.browser.base import BrowserElement
from app.settings import PROJECT_ROOT

CDP_DEFAULT_ACTION_TIMEOUT_MS = 30000
CDP_TIMEOUT_GRACE_SECONDS = 2.0
CDP_EVAL_TIMEOUT_SECONDS = 15.0

JOB51_ONLINE_RESUME_SAVE_TARGET_JS = r"""
() => {
  /* job51_online_resume_save_target */
  const attr = (el, name) => (el && el.getAttribute ? el.getAttribute(name) || "" : "");
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const visible = (el) => {
    if (!el) return false;
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" &&
      Number(style.opacity || "1") > 0 && rect.width > 0 && rect.height > 0;
  };
  const clickable = (el) => {
    let node = el;
    for (let depth = 0; node && depth < 5; depth += 1, node = node.parentElement) {
      if (!visible(node)) continue;
      const tag = String(node.tagName || "").toLowerCase();
      const role = attr(node, "role");
      const cursor = getComputedStyle(node).cursor || "";
      if (tag === "button" || tag === "a" || role === "button" || cursor === "pointer") {
        return node;
      }
    }
    return null;
  };
  const roots = Array.from(document.querySelectorAll(
    ".con.con-ehire, .imresume-container, .resume-preview, " +
      "#IMResumePrint, .el-dialog, [role='dialog']"
  )).filter(visible);
  const root = roots.find((item) => item.matches(".con.con-ehire")) ||
    roots.find((item) => item.id === "IMResumePrint") || roots.at(-1);
  if (!root) {
    return { found: false, reason: "online_resume_preview_root_not_found" };
  }
  const rootRect = root.getBoundingClientRect();
  const seen = new Set();
  const controls = Array.from(root.querySelectorAll(
    "button, a, [role='button'], i, svg, use, span, div"
  )).map((node) => {
    const control = clickable(node);
    if (!control || seen.has(control)) return null;
    seen.add(control);
    const rect = control.getBoundingClientRect();
    const icon = control.querySelector("i, svg, use");
    const label = [
      text(control), attr(control, "title"), attr(control, "aria-label"),
      attr(control, "class"), attr(icon, "class"), attr(icon, "href"),
      attr(icon, "xlink:href")
    ].join(" ");
    return { control, rect, label };
  }).filter(Boolean).filter((item) => {
    const rect = item.rect;
    return rect.width >= 12 && rect.width <= 80 && rect.height >= 12 && rect.height <= 80 &&
      rect.top >= rootRect.top && rect.top <= rootRect.top + 110 &&
      rect.right <= rootRect.right + 8 && rect.right >= rootRect.right - 280;
  });
  const semantic = controls.filter((item) => {
    const positive = /下载|保存|存储|导出|download|save|export/i.test(item.label);
    const negative = /转发|收藏|打印|分享|微信|forward|favorite|collect|print|share|wechat/i.test(
      item.label
    );
    return positive && !negative;
  }).sort((a, b) => b.rect.left - a.rect.left);
  const ordered = [...controls].sort((a, b) => a.rect.left - b.rect.left);
  const cluster = ordered.find((item, index) => {
    const next = ordered.slice(index + 1, index + 4);
    if (next.length !== 3) return false;
    const labels = next.map((entry) => entry.label);
    if (!/收藏|favorite|collect/i.test(labels[0])) return false;
    if (!/转发|forward|share/i.test(labels[1])) return false;
    if (!/打印|print/i.test(labels[2])) return false;
    const sequence = [item, ...next];
    return sequence.every((entry, offset) => {
      if (offset === 0) return true;
      const previous = sequence[offset - 1];
      const gap = entry.rect.left - previous.rect.right;
      return Math.abs(entry.rect.top - item.rect.top) <= 8 && gap >= -4 && gap <= 24;
    });
  }) || null;
  const target = semantic[0] || cluster;
  if (!target) {
    return {
      found: false,
      reason: "online_resume_save_icon_not_found",
      candidates: controls.slice(0, 12).map((item) => ({
        label: item.label.slice(0, 120),
        x: Math.round(item.rect.left),
        y: Math.round(item.rect.top),
      })),
    };
  }
  const marker = "data-codex-job51-save-target";
  document.querySelectorAll(`[${marker}]`).forEach((item) => item.removeAttribute(marker));
  target.control.setAttribute(marker, "trusted");
  return {
    found: true,
    trusted: true,
    x: target.rect.left + target.rect.width / 2,
    y: target.rect.top + target.rect.height / 2,
    source: semantic[0]
      ? "job51_toolbar_semantic_save"
      : "job51_toolbar_save_before_named_cluster",
    label: target.label.slice(0, 120),
    selector: `[${marker}='trusted']`,
  };
}
"""


class PlaywrightElement:
    """BrowserElement 的 Playwright Locator 包装。"""

    def __init__(self, locator: Any) -> None:
        self.locator = locator

    async def click(self, timeout_ms: int | None = None) -> None:
        kwargs = {"timeout": timeout_ms} if timeout_ms is not None else {}
        effective_timeout_ms = (
            timeout_ms if timeout_ms is not None else CDP_DEFAULT_ACTION_TIMEOUT_MS
        )
        await asyncio.wait_for(
            self.locator.click(**kwargs),
            timeout=max(effective_timeout_ms, 0) / 1000 + CDP_TIMEOUT_GRACE_SECONDS,
        )

    async def fill(self, value: str, timeout_ms: int | None = None) -> None:
        kwargs = {"timeout": timeout_ms} if timeout_ms is not None else {}
        effective_timeout_ms = (
            timeout_ms if timeout_ms is not None else CDP_DEFAULT_ACTION_TIMEOUT_MS
        )
        await asyncio.wait_for(
            self.locator.fill(value, **kwargs),
            timeout=max(effective_timeout_ms, 0) / 1000 + CDP_TIMEOUT_GRACE_SECONDS,
        )

    async def text(self) -> str:
        return await self.locator.inner_text()

    async def attr(self, name: str) -> str | None:
        return await self.locator.get_attribute(name)


class PlaywrightCDPPage:
    """BrowserPage 的 Playwright-CDP 实现。"""

    def __init__(self, page: Any, *, name: str = "") -> None:
        self.page = page
        self.name = name
        self.reliable_actions: list[dict[str, object]] = []
        self._blocked_popup_url_parts: set[str] = set()

    async def goto(self, url: str) -> None:
        await self.page.goto(url, wait_until="domcontentloaded")

    async def query(self, selector: str) -> BrowserElement | None:
        locator = self.page.locator(selector).first
        return PlaywrightElement(locator) if await locator.count() else None

    async def query_all(self, selector: str) -> list[BrowserElement]:
        locator = self.page.locator(selector)
        return [PlaywrightElement(locator.nth(index)) for index in range(await locator.count())]

    async def click(self, selector: str, timeout_ms: int | None = None) -> bool:
        element = await self.query(selector)
        if element is None:
            return False
        await element.click(timeout_ms=timeout_ms)
        return True

    async def fill(self, selector: str, value: str, timeout_ms: int | None = None) -> bool:
        element = await self.query(selector)
        if element is None:
            return False
        await element.fill(value, timeout_ms=timeout_ms)
        return True

    async def press(self, selector: str, key: str, timeout_ms: int | None = None) -> bool:
        locator = self.page.locator(selector).last
        if not await locator.count():
            return False
        kwargs = {"timeout": timeout_ms} if timeout_ms is not None else {}
        await locator.focus(**kwargs)
        await self.page.keyboard.press(key)
        return True

    async def text(self, selector: str | None = None) -> str:
        if selector is None:
            return await self.page.inner_text("body")
        element = await self.query(selector)
        return await element.text() if element else ""

    async def eval_js(self, script: str, arg: Any | None = None) -> Any:
        operation = (
            self.page.evaluate(script, arg)
            if arg is not None
            else self.page.evaluate(script)
        )
        return await asyncio.wait_for(operation, timeout=CDP_EVAL_TIMEOUT_SECONDS)

    async def click_and_download(
        self,
        script: str,
        arg: Any | None = None,
        timeout_ms: int = 15000,
    ) -> dict[str, Any]:
        """执行点击脚本并捕获真实浏览器下载文件。"""

        clicked: Any = {}
        try:
            if "#sensor_imresume_download" in script or "sensor_imresume_download" in script:
                return await self._click_job51_online_resume_download(timeout_ms=timeout_ms)
            if "zhilian_view_attachment_resume_download" in script:
                return await self._click_zhilian_attachment_resume_download(
                    timeout_ms=timeout_ms
                )
            async with self.page.expect_download(timeout=timeout_ms) as download_info:
                clicked = await self.eval_js(script, arg)
            download = await download_info.value
            path = await download.path()
            filename = str(download.suggested_filename or "")
            if path is None:
                target = Path(gettempdir()) / (filename or "job51_resume_download")
                await download.save_as(str(target))
                path = str(target)
            return {
                "ok": True,
                "clicked": clicked,
                "filename": filename,
                "bytes": Path(path).read_bytes(),
                "path": str(path),
            }
        except Exception as error:
            return {
                "ok": False,
                "clicked": clicked,
                "reason": "download_not_captured",
                "error": str(error),
            }

    async def install_url_popup_blocker(self, blocked_url_part: str) -> dict[str, Any]:
        """Close future popup tabs whose URL contains ``blocked_url_part``."""

        part = str(blocked_url_part or "").strip()
        if not part:
            return {"installed": False, "reason": "empty_blocked_url_part"}
        if part in self._blocked_popup_url_parts:
            return {"installed": True, "alreadyInstalled": True, "blockedUrlPart": part}
        self._blocked_popup_url_parts.add(part)

        def on_page(popup: Any) -> None:
            asyncio.create_task(self._close_blocked_popup(popup))

        self.page.context.on("page", on_page)
        return {"installed": True, "blockedUrlPart": part}

    async def _close_blocked_popup(self, popup: Any) -> None:
        for _ in range(50):
            try:
                url = str(popup.url or "")
                if any(part in url for part in self._blocked_popup_url_parts):
                    await popup.close()
                    return
                await popup.wait_for_timeout(100)
            except Exception:
                return

    async def _click_zhilian_attachment_resume_download(self, timeout_ms: int) -> dict[str, Any]:
        """Capture Zhilian attachments from a stable PDF tab or a transient download."""

        clicked: dict[str, Any] = {}
        target_page = self.page
        opened_new_page = False
        page_task: asyncio.Task[Any] | None = None
        download_task: asyncio.Task[Any] | None = None
        source_page_url = self._safe_page_url(self.page)
        behavior = await self._setup_zhilian_uuid_download_behavior()
        download_dir = Path(str(behavior.get("downloadPath") or "")) if behavior.get("ok") else None
        before_files = self._download_directory_snapshot(download_dir)
        try:
            toolbar_view = self.page.locator(".session-new-action a.km-button").filter(
                has_text="查看附件简历"
            ).last
            if await toolbar_view.count():
                view = toolbar_view
                entry_source = "toolbar_anchor"
            else:
                detail_view = self.page.locator(
                    ".im-resume-detail .newest-attach-resume"
                ).last
                if await detail_view.count():
                    view = detail_view
                    entry_source = "resume_detail_attachment"
                else:
                    view = self.page.get_by_text("查看附件简历").last
                    entry_source = "generic_text_fallback"
            if not await view.count():
                return {
                    "ok": False,
                    "clicked": clicked,
                    "reason": "view_attachment_button_not_found",
                }
            page_task = asyncio.create_task(
                self.page.context.wait_for_event("page", timeout=5000)
            )
            page_waiter = getattr(self.page, "wait_for_event", None)
            if callable(page_waiter):
                download_task = asyncio.create_task(
                    page_waiter("download", timeout=max(min(timeout_ms, 5000), 1))
                )
            click_error = ""
            try:
                await view.click(timeout=5000)
            except Exception as error:
                click_error = str(error)
            clicked = {
                "clicked": not bool(click_error),
                "source": "zhilian_view_attachment_click",
                "entrySource": entry_source,
                "downloadBehavior": behavior,
            }
            if click_error:
                clicked["clickError"] = click_error
            event_tasks = {task for task in (page_task, download_task) if task is not None}
            if event_tasks:
                await asyncio.wait(
                    event_tasks,
                    timeout=max(min(timeout_ms, 5000), 1) / 1000,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            popup = await self._attachment_task_result(page_task)
            if popup is not None:
                target_page = popup
                opened_new_page = target_page is not self.page
                clicked["clicked"] = True
                clicked["openedPage"] = True
                clicked["popupInitialUrl"] = self._safe_page_url(target_page)
            else:
                clicked["openedPage"] = False

            direct_download = await self._attachment_task_result(download_task)
            if direct_download is not None:
                clicked["clicked"] = True
                direct = await self._download_event_payload(
                    direct_download,
                    download_dir=download_dir,
                    source="direct_attachment_download",
                )
                if direct.get("ok"):
                    return {"clicked": clicked, **direct}

            popup_url = str(clicked.get("popupInitialUrl") or "")
            if opened_new_page and popup_url:
                popup_fetch = await self._fetch_zhilian_temporary_url(popup_url)
                clicked["popupUrlFetch"] = {
                    key: value for key, value in popup_fetch.items() if key != "bytes"
                }
                if popup_fetch.get("ok") and popup_fetch.get("bytes"):
                    return {
                        "ok": True,
                        "clicked": clicked,
                        "filename": popup_fetch.get("filename")
                        or "zhilian_resume_attachment",
                        "bytes": popup_fetch["bytes"],
                        "path": "",
                        "source": "zhilian_popup_url_fetch",
                    }

            if opened_new_page and self._page_is_closed(target_page):
                clicked["popupClosedBeforeCapture"] = True
                direct_download = await self._attachment_task_result(
                    download_task,
                    timeout_seconds=max(min(timeout_ms, 5000), 1) / 1000,
                )
                if direct_download is not None:
                    direct = await self._download_event_payload(
                        direct_download,
                        download_dir=download_dir,
                        source="direct_attachment_download",
                    )
                    if direct.get("ok"):
                        return {"clicked": clicked, **direct}
                uuid_download = await self._wait_for_new_download_file(
                    download_dir,
                    before_files,
                    timeout_ms=timeout_ms,
                )
                if uuid_download.get("ok"):
                    return {"clicked": clicked, **uuid_download}
                return {
                    "ok": False,
                    "clicked": clicked,
                    "reason": "popup_closed_before_capture",
                    "download": uuid_download,
                }
            target_page_url = self._safe_page_url(target_page)
            target_can_hold_attachment = opened_new_page or bool(
                target_page_url and target_page_url != source_page_url
            )
            if target_can_hold_attachment:
                try:
                    await target_page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                if self._page_is_closed(target_page):
                    clicked["popupClosedBeforeCapture"] = opened_new_page
                else:
                    fetched = await self._fetch_current_page_bytes(target_page)
                    if fetched.get("ok") and fetched.get("bytes"):
                        return {
                            "ok": True,
                            "clicked": clicked,
                            "filename": fetched.get("filename") or "zhilian_resume.pdf",
                            "bytes": fetched["bytes"],
                            "path": "",
                            "source": "opened_pdf_url",
                        }
                    if not self._page_is_closed(target_page):
                        viewer_download = await self._click_pdf_viewer_download(
                            target_page,
                            timeout_ms,
                        )
                        if viewer_download.get("ok"):
                            return {"clicked": clicked, **viewer_download}

            direct_download = await self._attachment_task_result(
                download_task,
                timeout_seconds=max(min(timeout_ms, 5000), 1) / 1000,
            )
            if direct_download is not None:
                direct = await self._download_event_payload(
                    direct_download,
                    download_dir=download_dir,
                    source="direct_attachment_download",
                )
                if direct.get("ok"):
                    return {"clicked": clicked, **direct}
            uuid_download = await self._wait_for_new_download_file(
                download_dir,
                before_files,
                timeout_ms=timeout_ms,
            )
            if uuid_download.get("ok"):
                return {"clicked": clicked, **uuid_download}
            if clicked.get("popupClosedBeforeCapture"):
                return {
                    "ok": False,
                    "clicked": clicked,
                    "reason": "popup_closed_before_capture",
                    "download": uuid_download,
                }
            return {
                "ok": False,
                "clicked": clicked,
                "reason": "download_not_captured",
                "download": uuid_download,
            }
        except Exception as error:
            return {
                "ok": False,
                "clicked": clicked,
                "reason": "download_not_captured",
                "error": str(error),
            }
        finally:
            await self._cancel_attachment_tasks(page_task, download_task)
            if (
                opened_new_page
                and target_page is not self.page
                and not self._page_is_closed(target_page)
            ):
                try:
                    await target_page.close()
                    clicked["closedPage"] = True
                except Exception as close_error:
                    clicked["closedPage"] = False
                    clicked["closeError"] = str(close_error)

    async def _setup_zhilian_uuid_download_behavior(self) -> dict[str, Any]:
        download_dir = PROJECT_ROOT / "data" / "downloads" / "_browser_uuid" / "zhilian"
        try:
            download_dir.mkdir(parents=True, exist_ok=True)
            session = await self.page.context.new_cdp_session(self.page)
            await session.send(
                "Browser.setDownloadBehavior",
                {
                    "behavior": "allowAndName",
                    "downloadPath": str(download_dir),
                    "eventsEnabled": True,
                },
            )
        except Exception as error:
            return {
                "ok": False,
                "reason": "download_behavior_setup_failed",
                "error": str(error),
                "downloadPath": str(download_dir),
            }
        return {"ok": True, "downloadPath": str(download_dir)}

    @staticmethod
    def _download_directory_snapshot(download_dir: Path | None) -> dict[str, tuple[int, int]]:
        if download_dir is None or not download_dir.exists():
            return {}
        snapshot: dict[str, tuple[int, int]] = {}
        for item in download_dir.iterdir():
            try:
                if item.is_file():
                    stat = item.stat()
                    snapshot[item.name] = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue
        return snapshot

    async def _wait_for_new_download_file(
        self,
        download_dir: Path | None,
        before: dict[str, tuple[int, int]],
        *,
        timeout_ms: int,
    ) -> dict[str, Any]:
        if download_dir is None:
            return {"ok": False, "reason": "download_behavior_setup_failed"}
        deadline = asyncio.get_running_loop().time() + max(timeout_ms, 0) / 1000
        stable_sizes: dict[str, int] = {}
        while True:
            candidates: list[Path] = []
            try:
                candidates = sorted(
                    (item for item in download_dir.iterdir() if item.is_file()),
                    key=lambda item: item.stat().st_mtime_ns,
                    reverse=True,
                )
            except OSError:
                candidates = []
            for item in candidates:
                if item.name.endswith(".crdownload"):
                    continue
                try:
                    stat = item.stat()
                except OSError:
                    continue
                current = (stat.st_size, stat.st_mtime_ns)
                if before.get(item.name) == current or stat.st_size <= 0:
                    continue
                previous_size = stable_sizes.get(item.name)
                stable_sizes[item.name] = stat.st_size
                if previous_size != stat.st_size:
                    continue
                try:
                    return {
                        "ok": True,
                        "filename": item.name,
                        "bytes": item.read_bytes(),
                        "path": str(item),
                        "source": "zhilian_uuid_download",
                    }
                except OSError:
                    continue
            if asyncio.get_running_loop().time() >= deadline:
                return {"ok": False, "reason": "download_file_not_found"}
            await asyncio.sleep(0.2)

    async def _download_event_payload(
        self,
        download: Any,
        *,
        download_dir: Path | None,
        source: str,
    ) -> dict[str, Any]:
        filename = str(getattr(download, "suggested_filename", "") or "")
        try:
            path = await download.path()
        except Exception:
            path = None
        if path:
            artifact = Path(path)
            if not artifact.exists() and download_dir is not None:
                uuid_path = download_dir / artifact.name
                if uuid_path.exists():
                    artifact = uuid_path
            if artifact.exists():
                return {
                    "ok": True,
                    "filename": filename or artifact.name,
                    "bytes": artifact.read_bytes(),
                    "path": str(artifact),
                    "source": source,
                }
        try:
            target = Path(gettempdir()) / (filename or "zhilian_resume_download")
            await download.save_as(str(target))
            return {
                "ok": True,
                "filename": filename or target.name,
                "bytes": target.read_bytes(),
                "path": str(target),
                "source": source,
            }
        except Exception as error:
            return {"ok": False, "reason": "download_event_file_missing", "error": str(error)}

    @staticmethod
    async def _attachment_task_result(
        task: asyncio.Task[Any] | None,
        *,
        timeout_seconds: float = 0,
    ) -> Any | None:
        if task is None:
            return None
        if not task.done() and timeout_seconds > 0:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
            except Exception:
                return None
        if not task.done():
            return None
        try:
            return task.result()
        except Exception:
            return None

    @staticmethod
    async def _cancel_attachment_tasks(*tasks: asyncio.Task[Any] | None) -> None:
        pending = [task for task in tasks if task is not None and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    @staticmethod
    def _page_is_closed(page: Any) -> bool:
        checker = getattr(page, "is_closed", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return True

    @staticmethod
    def _safe_page_url(page: Any) -> str:
        try:
            return str(page.url or "")
        except Exception:
            return ""

    async def _fetch_current_page_bytes(self, page: Any) -> dict[str, Any]:
        try:
            payload = await page.evaluate(
                """
                async () => {
                  const url = location.href;
                  if (!/^https?:/i.test(url)) return { ok: false, reason: "non_http_url", url };
                  const response = await fetch(url, { credentials: "include" });
                  const buffer = await response.arrayBuffer();
                  const bytes = new Uint8Array(buffer);
                  let binary = "";
                  const chunk = 0x8000;
                  for (let index = 0; index < bytes.length; index += chunk) {
                    binary += String.fromCharCode(...bytes.slice(index, index + chunk));
                  }
                  const disposition = response.headers.get("content-disposition") || "";
                  const match = disposition.match(/filename\\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i);
                  return {
                    ok: response.ok,
                    status: response.status,
                    contentType: response.headers.get("content-type") || "",
                    filename: match ? decodeURIComponent(match[1]) : "",
                    bytesBase64: btoa(binary),
                    url,
                  };
                }
                """
            )
        except Exception as error:
            return {"ok": False, "reason": "fetch_pdf_url_failed", "error": str(error)}
        encoded = str(payload.get("bytesBase64") or "") if isinstance(payload, dict) else ""
        if not encoded:
            return {"ok": False, "reason": "fetch_pdf_url_empty", "payload": payload}
        try:
            content = base64.b64decode(encoded)
        except ValueError:
            return {"ok": False, "reason": "fetch_pdf_url_bad_base64", "payload": payload}
        return {
            "ok": bool(payload.get("ok")),
            "filename": str(payload.get("filename") or ""),
            "contentType": str(payload.get("contentType") or ""),
            "bytes": content,
            "url": str(payload.get("url") or ""),
        }

    async def _fetch_zhilian_temporary_url(self, url: str) -> dict[str, Any]:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "attachment.zhaopin.com"
            or parsed.path != "/resumeapi/parsev2/downloadFileTemporary"
        ):
            return {"ok": False, "reason": "untrusted_zhilian_attachment_url"}
        request = getattr(self.page.context, "request", None)
        getter = getattr(request, "get", None)
        if not callable(getter):
            return {"ok": False, "reason": "context_request_unavailable"}
        try:
            response = await getter(url, timeout=15000)
            content = await response.body()
            headers = dict(getattr(response, "headers", {}) or {})
            status = int(getattr(response, "status", 0) or 0)
            ok = bool(getattr(response, "ok", False))
        except Exception as error:
            return {
                "ok": False,
                "reason": "zhilian_attachment_url_fetch_failed",
                "error": str(error),
            }
        if not ok or not content:
            return {
                "ok": False,
                "reason": "zhilian_attachment_url_empty",
                "status": status,
            }
        content_type = str(headers.get("content-type") or "")
        if "text/html" in content_type.lower() or content.lstrip().lower().startswith(b"<html"):
            return {
                "ok": False,
                "reason": "zhilian_attachment_url_returned_html",
                "status": status,
                "contentType": content_type,
            }
        disposition = str(headers.get("content-disposition") or "")
        filename = ""
        if "filename=" in disposition.lower():
            filename = disposition.split("=", 1)[1].strip().strip('"\'')
        return {
            "ok": True,
            "status": status,
            "contentType": content_type,
            "filename": filename,
            "bytes": content,
        }

    async def _click_pdf_viewer_download(
        self,
        page: Any,
        timeout_ms: int,
    ) -> dict[str, Any]:
        selectors = (
            "viewer-toolbar #downloads",
            "viewer-download-controls #download",
            "cr-icon-button#download",
            "#download",
            "[title*='下载']",
            "[aria-label*='下载']",
        )
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if not await locator.count():
                    continue
                async with page.expect_download(timeout=timeout_ms) as download_info:
                    await locator.click(timeout=5000)
                download = await download_info.value
                path = await download.path()
                filename = str(download.suggested_filename or "")
                if path is None:
                    target = Path(gettempdir()) / (filename or "zhilian_resume_download")
                    await download.save_as(str(target))
                    path = str(target)
                return {
                    "ok": True,
                    "filename": filename,
                    "bytes": Path(path).read_bytes(),
                    "path": str(path),
                    "source": f"pdf_viewer_download:{selector}",
                }
            except Exception:
                continue
        return {"ok": False, "reason": "pdf_viewer_download_button_not_found"}

    async def _click_job51_online_resume_download(self, timeout_ms: int) -> dict[str, Any]:
        """51job 在线简历保存必须使用可信点击并确认弹窗。"""

        clicked: dict[str, Any] = {}
        behavior = await self._setup_job51_uuid_download_behavior()
        if not behavior.get("ok"):
            return {
                "ok": False,
                "clicked": clicked,
                "reason": "download_behavior_setup_failed",
                "error": behavior.get("error") or "",
                "downloadPath": behavior.get("downloadPath") or "",
            }
        try:
            save = self.page.locator("#sensor_imresume_download").first
            if await save.count() and await save.is_visible():
                await save.click(timeout=5000)
                clicked = {"clicked": True, "source": "job51_trusted_save_click"}
            else:
                target = await self.page.evaluate(JOB51_ONLINE_RESUME_SAVE_TARGET_JS)
                if not isinstance(target, dict) or not target.get("found"):
                    return {
                        "ok": False,
                        "clicked": clicked,
                        "reason": "online_resume_export_not_available",
                        "target": target if isinstance(target, dict) else {},
                    }
                source = str(target.get("source") or "")
                if target.get("trusted") is not True or source not in {
                    "job51_toolbar_semantic_save",
                    "job51_toolbar_save_before_named_cluster",
                }:
                    return {
                        "ok": False,
                        "clicked": clicked,
                        "reason": "online_resume_save_target_untrusted",
                        "target": target,
                    }
                selector = str(target.get("selector") or "").strip()
                if not selector:
                    return {
                        "ok": False,
                        "clicked": clicked,
                        "reason": "online_resume_save_target_untrusted",
                        "target": target,
                    }
                marked_target = self.page.locator(selector).first
                if not await marked_target.count() or not await marked_target.is_visible():
                    return {
                        "ok": False,
                        "clicked": clicked,
                        "reason": "online_resume_save_target_stale",
                        "target": target,
                    }
                first_box = await marked_target.bounding_box(timeout=3000)
                if not first_box:
                    return {
                        "ok": False,
                        "clicked": clicked,
                        "reason": "online_resume_save_target_stale",
                        "target": target,
                    }
                x = float(first_box.get("x") or 0) + float(first_box.get("width") or 0) / 2
                y = float(first_box.get("y") or 0) + float(first_box.get("height") or 0) / 2
                if x <= 0 or y <= 0:
                    return {
                        "ok": False,
                        "clicked": clicked,
                        "reason": "online_resume_save_target_invalid",
                        "target": target,
                    }
                await self.page.mouse.move(x, y, steps=6)
                await self.page.wait_for_timeout(120)
                latest_box = await marked_target.bounding_box(timeout=3000)
                if not latest_box:
                    return {
                        "ok": False,
                        "clicked": clicked,
                        "reason": "online_resume_save_target_stale",
                        "target": target,
                    }
                x = float(latest_box.get("x") or 0) + float(
                    latest_box.get("width") or 0
                ) / 2
                y = float(latest_box.get("y") or 0) + float(
                    latest_box.get("height") or 0
                ) / 2
                await self.page.mouse.move(x, y, steps=3)
                await self.page.mouse.click(x, y)
                clicked = {
                    "clicked": True,
                    "source": source,
                    "label": str(target.get("label") or "")[:120],
                    "x": round(x),
                    "y": round(y),
                }
            dialog = self.page.locator(".el-dialog:visible").filter(has_text="保存到本地").last
            try:
                await dialog.wait_for(state="visible", timeout=4000)
            except Exception:
                return {
                    "ok": False,
                    "clicked": clicked,
                    "reason": "online_resume_save_dialog_not_visible",
                }
            if not await dialog.count() or not await dialog.is_visible():
                return {
                    "ok": False,
                    "clicked": clicked,
                    "reason": "online_resume_save_dialog_not_visible",
                }
            pdf = dialog.locator("button").filter(has_text="Pdf").first
            if await pdf.count():
                try:
                    await pdf.click(timeout=8000)
                    clicked["pdfSelected"] = True
                except Exception as error:
                    clicked["pdfSelected"] = False
                    clicked["pdfSelectError"] = str(error)
            confirm = dialog.locator("button.el-button--primary").filter(has_text="确定").last
            if not await confirm.count() or not await confirm.is_visible():
                return {
                    "ok": False,
                    "clicked": clicked,
                    "reason": "online_resume_save_confirm_not_visible",
                }
            async with self.page.expect_download(timeout=timeout_ms) as download_info:
                await confirm.click(timeout=10000)
                clicked["confirmed"] = True
            download = await download_info.value
            path = await download.path()
            filename = str(download.suggested_filename or "")
            if path:
                artifact = Path(path)
                uuid_path = Path(str(behavior.get("downloadPath") or "")) / artifact.name
                if not artifact.exists() and uuid_path.exists():
                    path = str(uuid_path)
            if path is None:
                target = Path(gettempdir()) / (filename or "job51_resume_download")
                await download.save_as(str(target))
                path = str(target)
            return {
                "ok": True,
                "clicked": clicked,
                "filename": filename,
                "bytes": Path(path).read_bytes(),
                "path": str(path),
            }
        except Exception as error:
            export_status = await self._job51_export_status_dialog()
            if clicked.get("confirmed") and export_status.get("queued"):
                return {
                    "ok": False,
                    "clicked": clicked,
                    "reason": "online_resume_export_queued_no_file",
                    "exportQueued": True,
                    "exportDialog": export_status,
                    "error": str(error),
                }
            return {
                "ok": False,
                "clicked": clicked,
                "reason": "download_not_captured",
                "error": str(error),
            }

    async def _job51_export_status_dialog(self) -> dict[str, Any]:
        dialog = self.page.locator(".el-message-box__wrapper:visible").last
        try:
            if not await dialog.count() or not await dialog.is_visible():
                return {"queued": False, "reason": "export_status_dialog_not_visible"}
            content = " ".join((await dialog.inner_text(timeout=2000)).split())
        except Exception as error:
            return {
                "queued": False,
                "reason": "export_status_dialog_read_failed",
                "error": str(error),
            }
        queued = "导出成功" in content and "导出记录" in content
        return {
            "queued": queued,
            "reason": "" if queued else "export_status_dialog_unrecognized",
            "text": content[:240],
        }

    async def _setup_job51_uuid_download_behavior(self) -> dict[str, Any]:
        download_dir = PROJECT_ROOT / "data" / "downloads" / "_browser_uuid" / "job51"
        try:
            download_dir.mkdir(parents=True, exist_ok=True)
            session = await self.page.context.new_cdp_session(self.page)
            await session.send(
                "Browser.setDownloadBehavior",
                {
                    "behavior": "allowAndName",
                    "downloadPath": str(download_dir),
                    "eventsEnabled": True,
                },
            )
        except Exception as error:
            return {
                "ok": False,
                "error": str(error),
                "downloadPath": str(download_dir),
            }
        return {"ok": True, "downloadPath": str(download_dir)}

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> bool:
        try:
            await self.page.wait_for_selector(selector, timeout=timeout_ms)
            return True
        except Exception:
            return False

    async def title(self) -> str:
        """返回页面标题，供健康检查和验证脚本打印。"""

        return await self.page.title()

    @property
    def url(self) -> str:
        """当前页面 URL。"""

        return str(self.page.url or "")


@dataclass
class PlaywrightCDPConnection:
    """一个 CDP 浏览器连接及其默认上下文。"""

    playwright: Any
    browser: Any
    context: Any

    async def ensure_page(
        self,
        *,
        name: str,
        url: str = "",
        url_hint: str = "",
    ) -> PlaywrightCDPPage:
        """按 URL hint 复用标签页；找不到时新建并导航。"""

        page = await self._find_ready_page(url_hint or url)
        if page is None:
            page = await self.context.new_page()
            if url:
                await page.goto(url, wait_until="domcontentloaded")
        elif url and self._is_blank(page):
            await page.goto(url, wait_until="domcontentloaded")
        return PlaywrightCDPPage(page, name=name)

    def _find_page(self, hint: str) -> Any | None:
        if not hint:
            return None
        host = urlparse(hint).hostname or hint
        for page in reversed(self.context.pages):
            if host and host in str(page.url or ""):
                return page
        return None

    async def _find_ready_page(self, hint: str) -> Any | None:
        if not hint:
            return None
        if "ehire.51job.com/Revision/chat" not in hint:
            return self._find_page(hint)
        fallback = None
        host = urlparse(hint).hostname or hint
        for page in reversed(self.context.pages):
            if not (host and host in str(page.url or "")):
                continue
            fallback = fallback or page
            if await self._has_job51_chat_rows(page):
                return page
        return fallback

    @staticmethod
    async def _has_job51_chat_rows(page: Any) -> bool:
        try:
            count = await asyncio.wait_for(
                page.evaluate(
                    "() => document.querySelectorAll('#conversation-list .list-item').length"
                ),
                timeout=2,
            )
        except Exception:
            return False
        return bool(count)

    @staticmethod
    def _is_blank(page: Any) -> bool:
        return str(page.url or "") in {"", "about:blank"}

    def is_connected(self) -> bool:
        """返回 CDP 连接是否仍然可用。"""

        return bool(self.browser and self.browser.is_connected())

    async def close(self) -> None:
        """关闭本进程持有的 Playwright 控制连接，不关闭远端浏览器进程。"""

        await self.playwright.stop()


async def connect_cdp_browser(cdp_url: str) -> PlaywrightCDPConnection:
    """连接已运行的 CloakBrowser CDP，并返回可复用连接。"""

    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(cdp_url)
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    return PlaywrightCDPConnection(playwright=playwright, browser=browser, context=context)


async def connect_cdp_page(cdp_url: str) -> PlaywrightCDPPage:
    """兼容旧调用：连接 CDP 并返回当前或新建页面。"""

    connection = await connect_cdp_browser(cdp_url)
    return await connection.ensure_page(name="default")
