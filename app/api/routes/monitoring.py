"""监控与处理明细路由。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.control_plane.dispatcher import Dispatcher
from app.domain.resume.repository import ResumeRepository
from app.evaluation.decision_log import recent_decisions

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/overview")
async def overview(request: Request) -> dict[str, object]:
    """返回今日概览、简历数量、worker 状态和决策日志摘要。"""

    repository: ResumeRepository | None = getattr(request.app.state, "resume_repository", None)
    repository = repository or ResumeRepository.from_settings()
    dispatcher: Dispatcher | None = getattr(request.app.state, "dispatcher", None)
    try:
        worker_statuses = await dispatcher.worker_statuses() if dispatcher else []
    except Exception as exc:  # pragma: no cover - 真实 worker 缺席时的控制面降级
        worker_statuses = [{"status": "unavailable", "error": str(exc)}]
    decisions = recent_decisions(20)
    return {
        "status": "ok",
        "resumeCount": repository.count(),
        "decisionCount": len(decisions),
        "recentDecisions": decisions,
        "workerStatuses": worker_statuses,
    }


@router.get("/decisions")
async def decisions(limit: int = 50) -> dict[str, object]:
    """查看自动化决策日志。"""

    safe_limit = max(1, min(200, limit))
    return {"items": recent_decisions(safe_limit)}
