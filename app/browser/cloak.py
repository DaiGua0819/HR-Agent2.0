"""CloakBrowser CDP 地址解析与健康探测。

本模块是项目内唯一的真实浏览器入口约定：代码只附着已经启动好的 CloakBrowser
CDP，不启动非 CloakBrowser，也不调用通用浏览器启动脚本。
"""

from __future__ import annotations

import asyncio
import os
from urllib.request import urlopen


def cdp_url_for(cdp_port: int) -> str:
    """按 owner 的 CDP 端口解析 CloakBrowser URL。"""

    candidates = [
        f"AGENT_CDP_{cdp_port}",
        f"CLOAK_CDP_{cdp_port}",
        "AGENT_CDP",
        "CLOAK_CDP",
    ]
    for name in candidates:
        value = os.getenv(name, "").strip()
        if value:
            return value.rstrip("/")
    return f"http://127.0.0.1:{cdp_port}"


async def ensure_cdp_ready(cdp_url: str, *, timeout_seconds: float = 5) -> bool:
    """检查 CDP `/json/version` 是否可访问。"""

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        if await _probe_cdp(cdp_url):
            return True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.25)


async def _probe_cdp(cdp_url: str) -> bool:
    url = f"{cdp_url.rstrip('/')}/json/version"

    def probe() -> bool:
        try:
            with urlopen(url, timeout=1) as response:
                return 200 <= response.status < 300
        except Exception:
            return False

    return await asyncio.to_thread(probe)
