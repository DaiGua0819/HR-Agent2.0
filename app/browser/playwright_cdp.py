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


class PlaywrightElement:
    """BrowserElement 的 Playwright Locator 包装。"""

    def __init__(self, locator: Any) -> None:
        self.locator = locator

    async def click(self, timeout_ms: int | None = None) -> None:
        kwargs = {"timeout": timeout_ms} if timeout_ms is not None else {}
        await self.locator.click(**kwargs)

    async def fill(self, value: str, timeout_ms: int | None = None) -> None:
        kwargs = {"timeout": timeout_ms} if timeout_ms is not None else {}
        await self.locator.fill(value, **kwargs)

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
        return (
            await self.page.evaluate(script, arg)
            if arg is not None
            else await self.page.evaluate(script)
        )

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

    async def _click_zhilian_attachment_resume_download(self, timeout_ms: int) -> dict[str, Any]:
        """Click Zhilian attachment card and capture opened PDF bytes."""

        clicked: dict[str, Any] = {}
        target_page = self.page
        try:
            view = self.page.get_by_text("查看附件简历").last
            if not await view.count():
                return {
                    "ok": False,
                    "clicked": clicked,
                    "reason": "view_attachment_button_not_found",
                }
            page_task = asyncio.create_task(
                self.page.context.wait_for_event("page", timeout=5000)
            )
            await view.click(timeout=5000)
            clicked = {"clicked": True, "source": "zhilian_view_attachment_click"}
            try:
                target_page = await page_task
                clicked["openedPage"] = True
            except Exception:
                clicked["openedPage"] = False
            try:
                await target_page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            await target_page.wait_for_timeout(1000)
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
            download = await self._click_pdf_viewer_download(target_page, timeout_ms)
            if download.get("ok"):
                return {"clicked": clicked, **download}
            return {
                "ok": False,
                "clicked": clicked,
                "reason": download.get("reason")
                or fetched.get("reason")
                or "download_not_captured",
                "fetch": fetched,
                "download": download,
            }
        except Exception as error:
            return {
                "ok": False,
                "clicked": clicked,
                "reason": "download_not_captured",
                "error": str(error),
            }

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
        try:
            async with self.page.expect_download(timeout=timeout_ms) as download_info:
                save = self.page.locator("#sensor_imresume_download").first
                await save.click(timeout=5000)
                clicked = {"clicked": True, "source": "job51_trusted_save_click"}
                await self.page.wait_for_timeout(1000)
                dialog = self.page.locator(".el-dialog").filter(has_text="保存到本地").last
                pdf = dialog.locator("button").filter(has_text="Pdf").first
                if await pdf.count():
                    await pdf.click(timeout=3000)
                    clicked["pdfSelected"] = True
                confirm = dialog.locator("button.el-button--primary").filter(has_text="确定").last
                await confirm.click(timeout=5000)
                clicked["confirmed"] = True
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
