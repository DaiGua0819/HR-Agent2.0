"""Administrator-only automation monitoring APIs."""

from __future__ import annotations

import mimetypes
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

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


@router.get("/resume-artifacts/{artifact_id}/download")
async def download_resume_artifact(artifact_id: str, request: Request) -> FileResponse:
    _require_admin(request)
    artifact = _service(request).get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="resume_artifact_not_found")
    path = Path(str(artifact.get("file_path") or ""))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="resume_artifact_file_not_found")
    candidate_name = str(artifact.get("candidate_name_from_platform") or "").strip()
    position = str(artifact.get("position") or "").strip()
    platform = str(artifact.get("platform") or "").strip()
    filename_parts = [part for part in (candidate_name, position, platform) if part]
    filename = f"{'_'.join(filename_parts)}{path.suffix.lower()}" if filename_parts else path.name
    return FileResponse(
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        filename=filename,
        content_disposition_type="attachment",
    )


@router.get("/runtime-status")
async def runtime_status(request: Request) -> dict[str, object]:
    _require_admin(request)
    return _service(request).runtime_status()
