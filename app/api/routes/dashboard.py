"""管理者驾驶舱聚合接口。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request

from app.control_plane.dispatcher import Dispatcher
from app.domain.resume.repository import ResumeRepository
from app.domain.resume_review.service import ResumeReviewService
from app.evaluation.decision_log import recent_decisions
from app.settings import load_settings

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/overview")
async def overview(request: Request) -> dict[str, object]:
    """返回经理首页所需的 KPI、服务状态和最近处理记录。"""

    settings = load_settings()
    repository: ResumeRepository | None = getattr(
        request.app.state,
        "resume_repository",
        None,
    )
    repository = repository or ResumeRepository.from_settings()
    review_service: ResumeReviewService | None = getattr(
        request.app.state,
        "resume_review_service",
        None,
    )
    dispatcher: Dispatcher | None = getattr(request.app.state, "dispatcher", None)
    services = await _worker_statuses(dispatcher)
    decisions = recent_decisions(12)
    pending_review = _pending_review_count(review_service)
    resume_count = repository.count()
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "dryRun": settings.dry_run,
        "environment": settings.environment,
        "kpis": _kpis(
            resume_count=resume_count,
            pending_review=pending_review,
            decision_count=len(decisions),
            services=services,
        ),
        "services": services,
        "recentRecords": [_decision_record(item) for item in decisions],
        "quickFilters": _quick_filters(),
    }


async def _worker_statuses(dispatcher: Dispatcher | None) -> list[dict[str, object]]:
    if dispatcher is None:
        return []
    try:
        raw_statuses = await dispatcher.worker_statuses()
    except Exception as exc:  # pragma: no cover - 真实 worker 不在线时的降级
        return [
            {
                "owner": "控制面",
                "platform": "all",
                "label": "Worker 状态",
                "status": "unavailable",
                "agentReady": False,
                "browserReady": False,
                "agentBusy": False,
                "error": str(exc),
            }
        ]
    return [_service_payload(item) for item in raw_statuses]


def _service_payload(status: dict[str, Any]) -> dict[str, object]:
    owner = str(status.get("owner") or "未知负责人")
    backend = str(status.get("browserBackend") or "")
    ready = bool(status.get("agentReady")) and bool(status.get("browserReady"))
    busy = bool(status.get("agentBusy"))
    return {
        "owner": owner,
        "platform": str(status.get("platform") or "all"),
        "label": owner if backend else f"{owner} worker",
        "status": "busy" if busy else "ready" if ready else str(status.get("status") or "unknown"),
        "agentReady": bool(status.get("agentReady")),
        "browserReady": bool(status.get("browserReady")),
        "cdpReady": bool(status.get("cdpReady")),
        "agentBusy": busy,
        "browserBackend": backend,
        "pageCount": int(status.get("pageCount") or 0),
        "dryRun": bool(status.get("dryRun", load_settings().dry_run)),
        "paused": status.get("paused") or [],
        "error": str(status.get("error") or ""),
    }


def _pending_review_count(service: ResumeReviewService | None) -> int:
    if service is None:
        return 0
    try:
        return len(service.shared_admin_queue())
    except Exception:
        return 0


def _kpis(
    *,
    resume_count: int,
    pending_review: int,
    decision_count: int,
    services: list[dict[str, object]],
) -> list[dict[str, object]]:
    worker_ready = len(
        [
            item
            for item in services
            if item.get("agentReady") and item.get("browserReady")
        ]
    )
    worker_busy = len([item for item in services if item.get("agentBusy")])
    return [
        {"key": "resumeCount", "label": "简历总数", "value": resume_count, "tone": "info"},
        {"key": "pendingReview", "label": "待我处理", "value": pending_review, "tone": "warning"},
        {"key": "decisionCount", "label": "最近决策", "value": decision_count, "tone": "info"},
        {"key": "workerReady", "label": "服务就绪", "value": worker_ready, "tone": "success"},
        {"key": "workerBusy", "label": "正在处理", "value": worker_busy, "tone": "primary"},
    ]


def _decision_record(event: dict[str, Any]) -> dict[str, object]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else event
    candidate_source = (
        payload.get("candidateName")
        or payload.get("candidate")
        or payload.get("conversationId")
        or payload.get("conversation_id")
        or "未命名候选人"
    )
    candidate = _candidate_name(candidate_source)
    position = (
        payload.get("position")
        or payload.get("jobType")
        or (candidate_source.get("applied_position") if isinstance(candidate_source, dict) else "")
        or ""
    )
    action = (
        payload.get("action")
        or payload.get("nextAction")
        or payload.get("event")
        or "decision"
    )
    result = payload.get("result") or payload.get("stage") or payload.get("decision") or ""
    return {
        "id": str(payload.get("id") or payload.get("conversationId") or ""),
        "time": str(payload.get("createdAt") or payload.get("created_at") or ""),
        "platform": str(payload.get("platform") or ""),
        "owner": str(payload.get("owner") or ""),
        "candidateName": _short_text(candidate, 28),
        "position": _short_text(position, 28),
        "action": _short_text(action, 32),
        "result": _short_text(result, 48),
        "dryRun": bool(payload.get("dryRun") or payload.get("dry_run")),
    }


def _candidate_name(value: object) -> object:
    if isinstance(value, dict):
        return (
            value.get("name")
            or value.get("label")
            or value.get("candidateName")
            or "未命名候选人"
        )
    return value


def _short_text(value: object, limit: int) -> str:
    if isinstance(value, dict):
        for key in ("reason", "message", "summary", "ok", "state"):
            if key in value:
                value = value[key]
                break
    text = str(value or "")
    return f"{text[:limit]}..." if len(text) > limit else text


def _quick_filters() -> list[dict[str, str]]:
    return [
        {"key": "unread", "label": "未看简历", "view": "resumes", "tab": "unread"},
        {"key": "suitable", "label": "合适待复核", "view": "queue", "tab": "queue"},
        {"key": "automation", "label": "自动化控制", "view": "automation", "tab": ""},
        {"key": "interviews", "label": "面试中心", "view": "interviews", "tab": ""},
    ]
