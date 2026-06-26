"""CloakBrowser CDP 连接与健康探测。

本模块复刻旧 `cloak_terminal_controller.py` 的关键连接约定：默认连接
`http://127.0.0.1:{port}`，也可通过 `CLOAK_CDP` / `AGENT_CDP` 以及端口、
平台专属环境变量覆盖。默认只检查并连接已运行的浏览器，自动启动需要显式打开
`HR_AGENT_CDP_AUTO_START=true`。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from urllib.request import urlopen

from app.core.constants import Platform


def cdp_url_for(cdp_port: int, *, platform: Platform | None = None) -> str:
    """按端口和平台解析 CDP URL。"""

    platform_key = f"_{platform.value.upper()}" if platform else ""
    candidates = [
        f"AGENT_CDP{platform_key}",
        f"CLOAK_CDP{platform_key}",
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


def profile_dir_for(cdp_port: int, fallback: Path | None = None) -> Path | None:
    """解析端口专属 profile 目录，仅作为启动脚本参数使用。"""

    for name in (f"CDP_PROFILE_DIR_{cdp_port}", f"CLOAK_PROFILE_DIR_{cdp_port}"):
        value = os.getenv(name, "").strip()
        if value:
            return Path(value)
    return fallback


def build_cloak_launch_args() -> list[str]:
    """返回可选启动脚本参数。

    真实浏览器启动方式与服务器安装形态相关，因此 Phase 7b 默认不自动调用。
    """

    script = os.getenv("HR_AGENT_CDP_START_SCRIPT", "start_cdp_browser.ps1")
    return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script]


async def ensure_cdp_ready(cdp_url: str, *, timeout_seconds: float = 5) -> bool:
    """检查 CDP `/json/version` 是否可访问。"""

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        if await _probe_cdp(cdp_url):
            return True
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.25)


async def maybe_start_cdp_browser(
    *,
    cdp_port: int,
    profile_dir: Path | None = None,
) -> bool:
    """在显式开启时调用启动脚本；默认返回 False。"""

    if os.getenv("HR_AGENT_CDP_AUTO_START", "").lower() not in {"1", "true", "yes"}:
        return False
    args = build_cloak_launch_args()
    args.extend(["-Port", str(cdp_port)])
    resolved_profile = profile_dir_for(cdp_port, profile_dir)
    if resolved_profile:
        args.extend(["-ProfileDir", str(resolved_profile)])
    subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW)
    return True


async def _probe_cdp(cdp_url: str) -> bool:
    url = f"{cdp_url.rstrip('/')}/json/version"

    def probe() -> bool:
        try:
            with urlopen(url, timeout=1) as response:
                return 200 <= response.status < 300
        except Exception:
            return False

    return await asyncio.to_thread(probe)
