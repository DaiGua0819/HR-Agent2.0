"""51job 页面导航动作。

只负责进入“人才沟通”页面并等待聊天壳层就绪；不处理岗位规则、不发送消息。
"""

from __future__ import annotations

import asyncio

from app.browser.base import BrowserPage
from app.browser.reliable_actions import reliable_click
from app.platforms.job51 import selectors


async def open_chat_page(page: BrowserPage) -> None:
    """进入 51job 人才沟通页，找不到入口时回工作台重试。"""

    if await _wait_chat_shell(page, timeout_ms=3000):
        return
    for attempt in range(2):
        click = await reliable_click(page, selectors.CHAT_ENTRY, label="51job人才沟通入口")
        await asyncio.sleep(1)
        if click.get("ok") and await _wait_chat_shell(page):
            return
        if attempt == 0:
            try:
                await page.goto(selectors.CHAT_HOME_URL)
            except Exception:
                if await _wait_chat_shell(page, timeout_ms=3000):
                    return
                raise
            await asyncio.sleep(3)


async def _wait_chat_shell(page: BrowserPage, timeout_ms: int = 12000) -> bool:
    """等待会话列表、输入框或未读筛选任一聊天页关键结构出现。"""

    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    while asyncio.get_running_loop().time() < deadline:
        if await _looks_like_chat_page(page):
            return True
        for selector in (
            selectors.THREAD_ITEM,
            selectors.CHAT_INPUT,
            selectors.UNREAD_FILTER,
        ):
            if await page.wait_for(selector, timeout_ms=1200):
                return True
        await asyncio.sleep(1)
    return False


async def _looks_like_chat_page(page: BrowserPage) -> bool:
    try:
        url = str(getattr(page, "url", "") or "").lower()
        body = await page.text()
    except Exception:
        return False
    return "ehire.51job.com/revision/chat" in url and all(
        term in body for term in ("人才沟通", "全部职位", "未读")
    )
