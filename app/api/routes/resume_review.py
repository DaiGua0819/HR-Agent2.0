"""简历审阅工作台 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.routes.auth import LOCAL_USER
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.domain.resume_review.service import ResumeReviewService

router = APIRouter(tags=["resume-review"])


class ReviewDecisionRequest(BaseModel):
    """合适/不合适/待补充请求。"""

    decision: str
    reason_tags: list[str] = Field(default_factory=list, alias="reasonTags")
    note: str = ""
    assign_to: str = Field(default="", alias="assignTo")


def _review_service(request: Request) -> ResumeReviewService:
    service = getattr(request.app.state, "resume_review_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="resume_review_service_not_configured")
    return service


def _resume_repository(request: Request) -> ResumeRepository:
    repository = getattr(request.app.state, "resume_repository", None)
    if repository is None:
        raise HTTPException(status_code=500, detail="resume_repository_not_configured")
    return repository


@router.get("/api/resumes/{resume_id}/review-context")
async def review_context(resume_id: str, request: Request) -> dict[str, object]:
    """返回审阅工作台上下文，并标记当前用户已看。"""

    record = _resume_repository(request).get(resume_id)
    if record is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    resume = Resume.from_record(record)
    return _review_service(request).context_for_resume(
        resume=resume,
        user_id=LOCAL_USER.id,
        mark_viewed=True,
    )


@router.post("/api/resumes/{resume_id}/view")
async def mark_viewed(resume_id: str, request: Request) -> dict[str, object]:
    """显式标记已看。"""

    if _resume_repository(request).get(resume_id) is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    state = _review_service(request).mark_viewed(resume_id, LOCAL_USER.id)
    return {"state": _state_payload(state)}


@router.post("/api/resumes/{resume_id}/review-decision")
async def review_decision(
    resume_id: str,
    payload: ReviewDecisionRequest,
    request: Request,
) -> dict[str, object]:
    """写入审阅结论。"""

    if _resume_repository(request).get(resume_id) is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    try:
        return _review_service(request).set_decision(
            resume_id=resume_id,
            user_id=LOCAL_USER.id,
            decision=payload.decision,
            reason_tags=payload.reason_tags,
            note=payload.note,
            assign_to=payload.assign_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/resume-review/queue")
async def review_queue(request: Request) -> dict[str, Any]:
    """返回当前用户的待处理队列。"""

    items = _review_service(request).queue_for_user(LOCAL_USER.id)
    return {"items": items, "total": len(items)}


def _state_payload(state: Any) -> dict[str, object]:
    return {
        "id": state.id,
        "userId": state.user_id,
        "resumeId": state.resume_id,
        "readStatus": state.read_status,
        "decision": state.decision,
        "reasonTags": state.reason_tags,
        "note": state.note,
        "assignedTo": state.assigned_to,
        "viewedAt": state.viewed_at,
        "createdAt": state.created_at,
        "updatedAt": state.updated_at,
    }
