"""worker HTTP 客户端封装。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.constants import Platform
from app.worker.runtime import WorkerRuntime


class WorkerClientProtocol(Protocol):
    """控制面需要的 worker 客户端能力。"""

    async def status(self) -> dict[str, Any]:
        """读取 worker 状态。"""

    async def process_messages(self, platform: Platform) -> dict[str, Any]:
        """处理某平台未读消息。"""

    async def proactive_contact(
        self, platform: Platform, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """主动联系。"""

    async def interview_invite(self, payload: dict[str, Any]) -> dict[str, Any]:
        """约面试。"""

    async def pause(self, platform: Platform) -> dict[str, Any]:
        """暂停平台。"""


@dataclass(frozen=True)
class WorkerClient:
    """访问单个 worker 的 HTTP 客户端。"""

    base_url: str
    status_timeout_seconds: float = 30
    automation_timeout_seconds: float = 600

    async def status(self) -> dict[str, Any]:
        async with self._client(self.status_timeout_seconds) as client:
            response = await client.get("/status")
            response.raise_for_status()
            return response.json()

    async def process_messages(self, platform: Platform) -> dict[str, Any]:
        async with self._client(self.automation_timeout_seconds) as client:
            response = await client.post(f"/automation/{platform.value}/process-messages")
            response.raise_for_status()
            return response.json()

    async def proactive_contact(
        self, platform: Platform, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        async with self._client(self.automation_timeout_seconds) as client:
            response = await client.post(
                f"/automation/{platform.value}/proactive-contact",
                json=payload or {},
            )
            response.raise_for_status()
            return response.json()

    async def interview_invite(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._client(self.automation_timeout_seconds) as client:
            response = await client.post("/interview-invite", json=payload)
            response.raise_for_status()
            return response.json()

    async def pause(self, platform: Platform) -> dict[str, Any]:
        async with self._client(self.status_timeout_seconds) as client:
            response = await client.post(f"/automation/{platform.value}/pause")
            response.raise_for_status()
            return response.json()

    def _client(self, timeout_seconds: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=timeout_seconds)


@dataclass
class InProcessWorkerClient:
    """测试用进程内 worker 客户端，不走真实网络。"""

    runtime: WorkerRuntime

    async def status(self) -> dict[str, Any]:
        return await self.runtime.status_payload()

    async def process_messages(self, platform: Platform) -> dict[str, Any]:
        return await self.runtime.process_messages(platform)

    async def proactive_contact(
        self, platform: Platform, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = payload or {}
        return await self.runtime.proactive_contact(
            platform,
            target_position=str(payload.get("targetPosition") or ""),
            dry_run=bool(payload.get("dryRun")),
        )

    async def interview_invite(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.runtime.interview_invite(payload)

    async def pause(self, platform: Platform) -> dict[str, Any]:
        return await self.runtime.pause(platform)
