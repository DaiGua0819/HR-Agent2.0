"""Playwright CDP 页面实现。

真实浏览器被封装在 `BrowserPage` 接口后面：平台动作层只看 query/click/fill/text
等最小方法，测试仍可继续使用 FakePage。这里连接的是已经运行的 CloakBrowser CDP，
不会主动启动浏览器，也不会绕过 dry-run 执行业务副作用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.browser.base import BrowserElement


class PlaywrightElement:
    """BrowserElement 的 Playwright Locator 包装。"""

    def __init__(self, locator: Any) -> None:
        self.locator = locator

    async def click(self) -> None:
        await self.locator.click()

    async def fill(self, value: str) -> None:
        await self.locator.fill(value)

    async def text(self) -> str:
        return await self.locator.inner_text()

    async def attr(self, name: str) -> str | None:
        return await self.locator.get_attribute(name)


class PlaywrightCDPPage:
    """BrowserPage 的 Playwright-CDP 实现。"""

    def __init__(self, page: Any, *, name: str = "") -> None:
        self.page = page
        self.name = name

    async def goto(self, url: str) -> None:
        await self.page.goto(url, wait_until="domcontentloaded")

    async def query(self, selector: str) -> BrowserElement | None:
        locator = self.page.locator(selector).first
        return PlaywrightElement(locator) if await locator.count() else None

    async def query_all(self, selector: str) -> list[BrowserElement]:
        locator = self.page.locator(selector)
        return [PlaywrightElement(locator.nth(index)) for index in range(await locator.count())]

    async def click(self, selector: str) -> bool:
        element = await self.query(selector)
        if element is None:
            return False
        await element.click()
        return True

    async def fill(self, selector: str, value: str) -> bool:
        element = await self.query(selector)
        if element is None:
            return False
        await element.fill(value)
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

        page = self._find_page(url_hint or url)
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
        for page in self.context.pages:
            if host and host in str(page.url or ""):
                return page
        return None

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
