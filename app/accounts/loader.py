"""从 `config/accounts.yaml` 加载账号配置。"""

from __future__ import annotations

from app.accounts.models import Account, WorkerConfig
from app.settings import AccountOpenOrder, load_settings


def load_workers() -> list[WorkerConfig]:
    """读取两个负责人 worker 配置。"""

    settings = load_settings()
    return [
        WorkerConfig(
            owner=worker.owner,
            port=worker.port,
            profile_dir=worker.resolved_profile_dir,
            cdp_port=worker.cdp_port,
            accounts=tuple(worker.accounts),
        )
        for worker in settings.workers
    ]


def load_accounts() -> list[Account]:
    """按 accounts.yaml 展开 2 人 x 3 平台账号。"""

    return [
        Account(owner=worker.owner, platform=platform)
        for worker in load_workers()
        for platform in worker.accounts
    ]


def load_open_order() -> list[AccountOpenOrder]:
    """读取控制面串行派发顺序。"""

    return list(load_settings().open_order)
