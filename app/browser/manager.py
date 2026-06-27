"""worker 独占浏览器管理器。

默认 fake 后端服务单元测试；真实后端只允许连接已运行的 CloakBrowser CDP。目标
拓扑是 `cloak`：一人一个 CDP 浏览器、三平台各一个标签页。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from app.browser.base import BrowserPage
from app.browser.cloak import cdp_url_for
from app.browser.fake_page import FakePage
from app.browser.lifecycle import BrowserHealth, check_browser_health, start_browser
from app.core.constants import Platform
from app.platforms.boss import selectors as boss_selectors
from app.platforms.zhilian import selectors as zhilian_selectors


@dataclass
class BrowserManager:
    """管理一个负责人 worker 的浏览器与三平台标签页。"""

    owner: str
    cdp_port: int
    backend: str = "fake"
    pages: dict[Platform, BrowserPage] = field(default_factory=dict)
    connection: Any | None = None
    started: bool = False

    async def start(self) -> None:
        """启动或连接独占浏览器，并准备三平台标签页。"""

        if self.started:
            return
        await start_browser(self.owner, self.cdp_port, backend=self.backend)
        if self.backend == "fake":
            self.pages = {
                Platform.BOSS: _fake_page(self.owner, Platform.BOSS),
                Platform.JOB51: _fake_page(self.owner, Platform.JOB51),
                Platform.ZHILIAN: _fake_page(self.owner, Platform.ZHILIAN),
            }
        elif self.backend == "cloak":
            self.pages, self.connection = await _connect_cdp_pages(self.cdp_port)
        else:
            raise ValueError(f"浏览器后端只允许 fake/cloak: {self.backend}")
        self.started = True

    async def close(self) -> None:
        """关闭本进程持有的 Playwright 控制连接，不关闭 CloakBrowser。"""

        if self.connection is not None:
            await self.connection.close()
        self.connection = None
        self.started = False

    async def health(self) -> BrowserHealth:
        """检查浏览器和页面是否可用。"""

        return await check_browser_health(self)

    def page_for(self, owner: str, platform: Platform) -> BrowserPage:
        """按 (owner, platform) 返回标签页。"""

        if owner != self.owner:
            raise KeyError(f"worker 只管理自己的页面: {self.owner} != {owner}")
        try:
            return self.pages[platform]
        except KeyError as error:
            raise KeyError(f"未找到平台页面: {owner}/{platform}") from error


async def _connect_cdp_pages(cdp_port: int) -> tuple[dict[Platform, BrowserPage], Any]:
    """连接目标拓扑：同一 CDP 浏览器下准备三平台标签页。"""

    from app.browser.playwright_cdp import connect_cdp_browser

    connection = await connect_cdp_browser(cdp_url_for(cdp_port))
    pages = {
        platform: await connection.ensure_page(
            name=platform.value,
            url=_chat_url_for(platform),
            url_hint=_url_hint_for(platform),
        )
        for platform in (Platform.BOSS, Platform.JOB51, Platform.ZHILIAN)
    }
    return pages, connection


def _chat_url_for(platform: Platform) -> str:
    if platform == Platform.BOSS:
        return boss_selectors.CHAT_URL
    if platform == Platform.ZHILIAN:
        return zhilian_selectors.CHAT_URL
    return os.getenv("JOB51_CHAT_URL", "https://ehire.51job.com/").strip()


def _url_hint_for(platform: Platform) -> str:
    if platform == Platform.BOSS:
        return "zhipin.com"
    if platform == Platform.ZHILIAN:
        return "zhaopin.com"
    return os.getenv("JOB51_URL_HINT", "51job.com").strip()


def _fake_page(owner: str, platform: Platform) -> FakePage:
    """构造可跑通共享 agent 的假页面。"""

    position = "销售管培生"
    common = {
        "id": f"{owner}-{platform.value}-conv",
        "name": "候选人",
        "position": position,
        "label": f"{owner} {platform.value} {position}",
        "latest_message": "你好",
        "unread_count": 1,
        "messages": [{"sender": "other", "text": "你好"}],
    }
    page = FakePage(conversations=[common])
    page.selected_recommend_position = "电气工程师"
    page.recommend_candidates = [
        {
            "name": "候选A",
            "card_text": "30岁 本科 电气工程",
            "resume_text": "自动化 PLC 项目",
        }
    ]
    return page
