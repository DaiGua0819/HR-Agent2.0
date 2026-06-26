"""平台 adapter 注册表。"""

from __future__ import annotations

from app.browser.base import BrowserPage
from app.core.constants import Platform
from app.platforms.base import PlatformAdapter
from app.platforms.boss.adapter import BossAdapter
from app.platforms.job51.adapter import Job51Adapter
from app.platforms.zhilian.adapter import ZhilianAdapter


def get_platform_adapter(
    platform: Platform,
    page: BrowserPage,
    *,
    owner: str,
    dry_run: bool | None = None,
) -> PlatformAdapter:
    """按平台返回 adapter 实例。"""

    if platform == Platform.BOSS:
        return BossAdapter(page, owner=owner, dry_run=dry_run)
    if platform == Platform.JOB51:
        return Job51Adapter(page, owner=owner, dry_run=dry_run)
    if platform == Platform.ZHILIAN:
        return ZhilianAdapter(page, owner=owner, dry_run=dry_run)
    raise NotImplementedError(f"Phase 2+ 注册平台 adapter: {platform}")
