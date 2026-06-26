"""账号与 worker 路由管理。"""

from __future__ import annotations

from dataclasses import dataclass

from app.accounts.loader import load_open_order, load_workers
from app.accounts.models import WorkerConfig
from app.core.constants import Platform
from app.settings import AccountOpenOrder


@dataclass(frozen=True)
class AccountRoute:
    """某负责人某平台应路由到哪个 worker。"""

    owner: str
    platform: Platform
    worker: WorkerConfig


class AccountManager:
    """提供 owner 和 (owner, platform) 的路由查询。"""

    def __init__(
        self,
        workers: list[WorkerConfig] | None = None,
        open_order: list[AccountOpenOrder] | None = None,
    ) -> None:
        self.workers = workers or load_workers()
        self.open_order = open_order or load_open_order()

    def worker_for_owner(self, owner: str) -> WorkerConfig:
        """按负责人查找 worker。"""

        for worker in self.workers:
            if worker.owner == owner:
                return worker
        raise KeyError(f"未找到负责人 worker: {owner}")

    def route_for_account(self, owner: str, platform: Platform) -> AccountRoute:
        """按负责人和平台查找账号路由。"""

        worker = self.worker_for_owner(owner)
        if platform not in worker.accounts:
            raise KeyError(f"worker 未配置平台账号: {owner}/{platform}")
        return AccountRoute(owner=owner, platform=platform, worker=worker)

    def worker_base_urls(self) -> dict[str, str]:
        """返回 owner 到 worker HTTP 地址的映射。"""

        return {worker.owner: worker.base_url for worker in self.workers}


def get_open_order() -> list[AccountOpenOrder]:
    """兼容旧调用：返回控制面串行打开/派发顺序。"""

    return AccountManager().open_order
