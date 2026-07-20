"""Administrator-only automation monitoring APIs."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.routes.auth import require_session_payload
from app.domain.automation_monitoring.service import AutomationMonitoringService

router = APIRouter(prefix="/api/automation-monitoring", tags=["automation-monitoring"])


def _service(request: Request) -> AutomationMonitoringService:
    service = getattr(request.app.state, "automation_monitoring_service", None)
    if not isinstance(service, AutomationMonitoringService):
        raise HTTPException(status_code=503, detail="automation_monitoring_unavailable")
    return service


def _require_admin(request: Request) -> None:
    session = require_session_payload(request)
    roles = session.get("roles")
    if not isinstance(roles, list) or not {"admin", "super_admin"} & set(roles):
        raise HTTPException(status_code=403, detail="monitoring_forbidden")


@router.get("/daily-summary")
async def daily_summary(
    request: Request,
    date: str = Query(default_factory=lambda: datetime.now().strftime("%Y-%m-%d")),
    platform: str = "",
    owner: str = "",
    job_type: str = "",
) -> dict[str, object]:
    _require_admin(request)
    return _service(request).daily_summary(
        date=date, platform=platform, owner=owner, job_type=job_type
    )


@router.get("/daily-details")
async def daily_details(
    request: Request,
    date: str,
    metric: str = "processedContacts",
    platform: str = "",
    owner: str = "",
    job_type: str = "",
    page: int = 1,
    page_size: int = 10,
) -> dict[str, object]:
    _require_admin(request)
    return _service(request).daily_details(
        date=date,
        metric=metric,
        platform=platform,
        owner=owner,
        job_type=job_type,
        page=page,
        page_size=page_size,
    )


@router.get("/runtime-status")
async def runtime_status(request: Request) -> dict[str, object]:
    _require_admin(request)
    return _service(request).runtime_status()
