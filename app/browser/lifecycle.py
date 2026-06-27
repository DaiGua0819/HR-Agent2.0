"""CloakBrowser 生命周期与健康检查。

真实浏览器必须由外部先启动为 CloakBrowser 并暴露 CDP；项目代码只做 CDP 探测和
附着，不启动非 CloakBrowser。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.browser.cloak import cdp_url_for, ensure_cdp_ready


@dataclass(frozen=True)
class BrowserHealth:
    """浏览器健康状态。"""

    browser_ready: bool
    cdp_ready: bool
    page_count: int
    backend: str


async def start_browser(owner: str, cdp_port: int, *, backend: str = "fake") -> dict[str, object]:
    """检查 fake 或 CloakBrowser CDP 后端是否可用。"""

    if backend == "fake":
        return {"owner": owner, "cdpPort": cdp_port, "backend": backend, "started": True}
    if backend != "cloak":
        raise ValueError(f"浏览器后端只允许 fake/cloak: {backend}")
    cdp_url = cdp_url_for(cdp_port)
    ready = await ensure_cdp_ready(cdp_url, timeout_seconds=2)
    if not ready:
        raise RuntimeError(f"CloakBrowser CDP 未就绪: {cdp_url}")
    return {
        "owner": owner,
        "cdpPort": cdp_port,
        "cdpUrl": cdp_url,
        "backend": backend,
        "started": True,
    }


async def check_browser_health(manager: Any) -> BrowserHealth:
    """检查浏览器和 CDP 是否可用。"""

    backend = str(getattr(manager, "backend", "unknown"))
    pages = getattr(manager, "pages", {}) or {}
    started = bool(getattr(manager, "started", False))
    connection = getattr(manager, "connection", None)
    cdp_ready = started if backend == "fake" else bool(connection and connection.is_connected())
    return BrowserHealth(
        browser_ready=started and bool(pages),
        cdp_ready=cdp_ready,
        page_count=len(pages),
        backend=backend,
    )


async def restart_browser(manager: Any) -> BrowserHealth:
    """崩溃重启入口；Phase 4 调用 manager.start() 恢复 fake/CDP 页面。"""

    manager.started = False
    manager.pages = {}
    await manager.start()
    return await check_browser_health(manager)
