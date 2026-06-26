"""健康检查路由。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.control_plane.dispatcher import Dispatcher
from app.settings import load_settings

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    """控制面最小健康检查。"""

    settings = load_settings()
    dispatcher: Dispatcher | None = getattr(request.app.state, "dispatcher", None)
    try:
        worker_statuses = await dispatcher.worker_statuses() if dispatcher else []
    except Exception as exc:  # pragma: no cover - worker 未启动时健康检查仍可返回控制面状态
        worker_statuses = [{"status": "unavailable", "error": str(exc)}]
    return {
        "status": "ok",
        "service": "control-plane",
        "workers": [{"owner": worker.owner, "port": worker.port} for worker in settings.workers],
        "workerStatuses": worker_statuses,
    }
