"""简历审阅工作台 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.routes.auth import current_user_id, require_session_payload
from app.auth.resume_scope import resume_visible_to_payload
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


class PushToAdminRequest(BaseModel):
    """成员把合适简历推送给管理员。"""

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
    _assert_resume_visible(request, resume)
    user_id = current_user_id(request)
    service = _review_service(request)
    context = service.context_for_resume(
        resume=resume,
        user_id=user_id,
        mark_viewed=True,
    )
    reviewer_decisions = service.reviewer_decisions_for_resumes([resume.id]).get(resume.id, [])
    context["reviewerDecisions"] = reviewer_decisions
    context["memberReviewStates"] = reviewer_decisions
    resume_payload = context.get("resume")
    if isinstance(resume_payload, dict):
        resume_payload["reviewerDecisions"] = reviewer_decisions
        resume_payload["memberReviewStates"] = reviewer_decisions
    return context


@router.post("/api/resumes/{resume_id}/view")
async def mark_viewed(resume_id: str, request: Request) -> dict[str, object]:
    """显式标记已看。"""

    record = _resume_repository(request).get(resume_id)
    if record is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    _assert_resume_visible(request, Resume.from_record(record))
    state = _review_service(request).mark_viewed(resume_id, current_user_id(request))
    return {"state": _state_payload(state)}


@router.post("/api/resumes/{resume_id}/review-decision")
async def review_decision(
    resume_id: str,
    payload: ReviewDecisionRequest,
    request: Request,
) -> dict[str, object]:
    """写入审阅结论。"""

    record = _resume_repository(request).get(resume_id)
    if record is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    session = _assert_resume_visible(request, Resume.from_record(record))
    try:
        return _review_service(request).set_decision(
            resume_id=resume_id,
            user_id=current_user_id(request),
            user_name=_session_user_name(session),
            decision=payload.decision,
            reason_tags=payload.reason_tags,
            note=payload.note,
            is_admin=_session_is_admin(session),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/resumes/{resume_id}/push-to-admin")
async def push_to_admin(
    resume_id: str,
    request: Request,
    payload: PushToAdminRequest | None = None,
) -> dict[str, object]:
    """成员确认后把合适简历推送到管理员待处理队列。"""

    record = _resume_repository(request).get(resume_id)
    if record is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    session = _assert_resume_visible(request, Resume.from_record(record))
    body = payload or PushToAdminRequest()
    try:
        return _review_service(request).push_to_admin(
            resume_id=resume_id,
            user_id=current_user_id(request),
            user_name=_session_user_name(session),
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/resume-review/queue")
async def review_queue(request: Request) -> dict[str, Any]:
    """返回当前用户的待处理队列。"""

    session = require_session_payload(request)
    if not _session_is_admin(session):
        raise HTTPException(status_code=403, detail="admin_queue_forbidden")
    items = _review_service(request).shared_admin_queue()
    items = _filter_visible_queue(items, session)
    return {"items": items, "total": len(items)}


def _filter_visible_queue(
    items: list[dict[str, object]],
    session: dict[str, object],
) -> list[dict[str, object]]:
    visible: list[dict[str, object]] = []
    for item in items:
        resume_payload = item.get("resume")
        if not isinstance(resume_payload, dict):
            continue
        resume = Resume.model_validate(resume_payload)
        if resume_visible_to_payload(resume, session):
            visible.append(item)
    return visible


def _assert_resume_visible(request: Request, resume: Resume) -> dict[str, object]:
    session = require_session_payload(request)
    if not resume_visible_to_payload(resume, session):
        raise HTTPException(status_code=403, detail="resume_forbidden")
    return session


def _session_is_admin(session: dict[str, object]) -> bool:
    roles = session.get("roles")
    return isinstance(roles, list) and bool({"super_admin", "admin"} & set(roles))


def _session_user_name(session: dict[str, object]) -> str:
    user = session.get("user")
    if not isinstance(user, dict):
        return ""
    return str(user.get("name") or "")


def _state_payload(state: Any) -> dict[str, object]:
    return {
        "id": state.id,
        "userId": state.user_id,
        "userName": state.user_name,
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
