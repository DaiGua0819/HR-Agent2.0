"""控制面任务派发器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.accounts.manager import AccountManager
from app.control_plane.worker_client import WorkerClient, WorkerClientProtocol
from app.core.constants import Platform
from app.orchestration.run_order import load_run_order


@dataclass
class DispatchResult:
    """一次派发结果。"""

    owner: str
    platform: Platform
    result: dict[str, Any]


@dataclass
class Dispatcher:
    """按账号路由把控制面任务串行派发给 worker。"""

    account_manager: AccountManager = field(default_factory=AccountManager)
    clients: dict[str, WorkerClientProtocol] | None = None
    dispatch_log: list[tuple[str, Platform]] = field(default_factory=list)

    def client_for_owner(self, owner: str) -> WorkerClientProtocol:
        """查找或创建 worker client。"""

        if self.clients and owner in self.clients:
            return self.clients[owner]
        worker = self.account_manager.worker_for_owner(owner)
        return WorkerClient(worker.base_url)

    async def dispatch_process_unread(
        self,
        owner: str,
        platform: Platform,
        *,
        exclude_ids: set[str] | None = None,
        batch_id: str = "",
    ) -> DispatchResult:
        """派发某负责人某平台未读处理。"""

        self.account_manager.route_for_account(owner, platform)
        self.dispatch_log.append((owner, platform))
        client = self.client_for_owner(owner)
        kwargs: dict[str, Any] = {}
        if exclude_ids:
            kwargs["exclude_ids"] = exclude_ids
        if batch_id:
            kwargs["batch_id"] = batch_id
        result = await client.process_messages(platform, **kwargs)
        return DispatchResult(owner=owner, platform=platform, result=result)

    async def process_all(self) -> dict[str, object]:
        """按 open_order 串行处理全部平台账号。"""

        start_index = len(self.dispatch_log)
        results: list[dict[str, Any]] = []
        for target in load_run_order(self.account_manager):
            item = await self.dispatch_process_unread(target.owner, target.platform)
            results.append(_result_payload(item))
        recent = self.dispatch_log[start_index:]
        return {
            "accepted": True,
            "mode": "serial",
            "order": [f"{owner}:{platform.value}" for owner, platform in recent],
            "results": results,
        }

    async def proactive_contact(
        self,
        owner: str,
        platform: Platform,
        payload: dict[str, Any] | None = None,
    ) -> DispatchResult:
        """派发主动联系任务。"""

        self.account_manager.route_for_account(owner, platform)
        result = await self.client_for_owner(owner).proactive_contact(platform, payload)
        return DispatchResult(owner=owner, platform=platform, result=result)

    async def interview_invite(self, owner: str, payload: dict[str, Any]) -> DispatchResult:
        """派发简历库约面试动作到负责人 worker。"""

        platform = Platform(str(payload.get("platform") or ""))
        self.account_manager.route_for_account(owner, platform)
        result = await self.client_for_owner(owner).interview_invite(payload)
        return DispatchResult(owner=owner, platform=platform, result=result)

    async def pause(self, owner: str, platform: Platform) -> DispatchResult:
        """派发暂停任务。"""

        self.account_manager.route_for_account(owner, platform)
        result = await self.client_for_owner(owner).pause(platform)
        return DispatchResult(owner=owner, platform=platform, result=result)

    async def worker_statuses(self) -> list[dict[str, Any]]:
        """聚合两个 worker 状态。"""

        statuses: list[dict[str, Any]] = []
        for worker in self.account_manager.workers:
            statuses.append(await self.client_for_owner(worker.owner).status())
        return statuses


async def dispatch_process_unread(
    owner: str,
    platform: Platform,
    *,
    exclude_ids: set[str] | None = None,
) -> dict[str, object]:
    """兼容旧调用：派发未读处理任务。"""

    result = await Dispatcher().dispatch_process_unread(
        owner,
        platform,
        exclude_ids=exclude_ids,
    )
    return _result_payload(result)


def _result_payload(item: DispatchResult) -> dict[str, Any]:
    return {"owner": item.owner, "platform": item.platform.value, "result": item.result}
