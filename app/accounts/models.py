"""账号与 worker 配置模型。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.constants import Platform


@dataclass(frozen=True)
class Account:
    """单个负责人在单个平台上的招聘账号。"""

    owner: str
    platform: Platform


@dataclass(frozen=True)
class WorkerConfig:
    """单 worker 的进程、浏览器与账号配置。"""

    owner: str
    port: int
    profile_dir: Path
    cdp_port: int
    accounts: tuple[Platform, ...]

    @property
    def base_url(self) -> str:
        """worker 本地 HTTP 地址。"""

        return f"http://127.0.0.1:{self.port}"


RecruitAccount = Account
