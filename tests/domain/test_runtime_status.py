"""Runtime status classification regression tests."""

from __future__ import annotations

import asyncio

from app.core.constants import Platform
from app.domain.automation_monitoring.runtime_status import build_runtime_statuses


class Page:
    def __init__(self, *, url: str, title: str) -> None:
        self.url = url
        self._title = title

    async def title(self) -> str:
        return self._title


class Browser:
    backend = "cloak"

    def __init__(self, page: Page) -> None:
        self.pages = {Platform.BOSS: page}


def test_boss_chat_security_query_is_ready() -> None:
    status = _boss_status(
        url="https://www.zhipin.com/web/chat/index?_security_check=1_123",
        title="BOSS直聘",
    )

    assert status.status == "ready"
    assert status.authenticated is True
    assert status.security_verification is False


def test_boss_verify_page_requires_security_verification() -> None:
    status = _boss_status(
        url="https://www.zhipin.com/web/user/verify.html",
        title="安全验证",
    )

    assert status.status == "security_verification"
    assert status.authenticated is False
    assert status.security_verification is True
    assert status.reason == "security_verification_required"


def _boss_status(*, url: str, title: str):
    statuses = asyncio.run(
        build_runtime_statuses(
            owner="宋峰峰",
            browser=Browser(Page(url=url, title=title)),
            agent_ready=True,
            browser_ready=True,
            cdp_ready=True,
            agent_busy=False,
        )
    )
    return next(item for item in statuses if item.platform == Platform.BOSS.value)
