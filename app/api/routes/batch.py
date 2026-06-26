"""批量简历解析路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.domain.batch.service import BatchService

router = APIRouter(prefix="/api/batch", tags=["batch"])


class BatchJobCreateRequest(BaseModel):
    """批量任务创建请求。"""

    model_config = ConfigDict(populate_by_name=True)

    parse_mode: str = Field(default="auto", alias="parseMode")
    files: list[dict[str, Any]] = Field(default_factory=list)


def _service(request: Request) -> BatchService:
    service = getattr(request.app.state, "batch_service", None)
    if service is None:
        service = BatchService()
        request.app.state.batch_service = service
    return service


@router.post("/jobs")
async def create_batch_job(
    payload: BatchJobCreateRequest,
    request: Request,
) -> dict[str, object]:
    """创建批量解析任务。"""

    job = _service(request).create_job(payload.parse_mode, payload.files)
    return job.to_dict()


@router.get("/jobs")
async def list_batch_jobs(request: Request) -> dict[str, object]:
    """列出批量任务。"""

    return {"items": [job.to_dict() for job in _service(request).list_jobs()]}


@router.get("/jobs/{job_id}")
async def get_batch_job(job_id: str, request: Request) -> dict[str, object]:
    """读取批量任务详情。"""

    job = _service(request).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="batch_job_not_found")
    return job.to_dict()


@router.post("/jobs/{job_id}/{action}")
async def update_batch_job_status(
    job_id: str,
    action: str,
    request: Request,
) -> dict[str, object]:
    """暂停、继续、取消或重试批量任务。"""

    action_to_status = {
        "pause": "paused",
        "resume": "running",
        "continue": "running",
        "cancel": "cancelled",
        "retry": "pending",
    }
    if action not in action_to_status:
        raise HTTPException(status_code=400, detail="unsupported_batch_action")
    job = _service(request).set_status(job_id, action_to_status[action])
    if job is None:
        raise HTTPException(status_code=404, detail="batch_job_not_found")
    return job.to_dict()
