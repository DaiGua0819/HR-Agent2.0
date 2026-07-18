"""worker FastAPI 接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI

from app.core.constants import Platform
from app.worker.runtime import WorkerRuntime


def create_worker_app(runtime: WorkerRuntime) -> FastAPI:
    """创建单 worker 应用。"""

    app = FastAPI(title=f"HR Agent Worker - {runtime.owner}")
    router = APIRouter()

    @app.on_event("startup")
    async def startup() -> None:
        await runtime.start()

    @router.get("/status")
    async def status() -> dict[str, object]:
        return await runtime.status_payload()

    @router.post("/automation/{platform}/process-messages")
    async def process_messages(
        platform: Platform,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        payload = payload or {}
        raw_exclude_ids = payload.get("excludeConversationIds")
        exclude_ids = (
            {str(item) for item in raw_exclude_ids if str(item)}
            if isinstance(raw_exclude_ids, list)
            else set()
        )
        return await runtime.process_messages(
            platform,
            exclude_ids=exclude_ids,
            batch_id=str(payload.get("batchId") or ""),
        )

    @router.post("/automation/{platform}/drain-messages")
    async def drain_messages(
        platform: Platform,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        payload = payload or {}
        return await runtime.drain_messages(
            platform,
            max_contacts=int(payload.get("maxContacts") or 300),
        )

    @router.post("/automation/{platform}/proactive-contact")
    async def proactive_contact(
        platform: Platform, payload: dict[str, Any] | None = None
    ) -> dict[str, object]:
        payload = payload or {}
        return await runtime.proactive_contact(
            platform,
            target_position=str(payload.get("targetPosition") or ""),
            dry_run=payload.get("dryRun"),
        )

    @router.post("/automation/{platform}/pause")
    async def pause(platform: Platform) -> dict[str, object]:
        return await runtime.pause(platform)

    @router.post("/interview-invite")
    async def interview_invite(payload: dict[str, Any] | None = None) -> dict[str, object]:
        return await runtime.interview_invite(payload)

    app.include_router(router)
    app.state.runtime = runtime
    return app
