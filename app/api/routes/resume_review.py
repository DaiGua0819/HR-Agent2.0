"""简历审阅工作台 API。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.routes.auth import current_user_id, require_session_payload
from app.api.routes.resumes import _resume_list_payload
from app.auth.resume_scope import allowed_job_types, resume_visible_to_payload
from app.domain.resume.job_types import canonical_resume_job_type
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
async def review_queue(
    request: Request,
    status: Literal["pending", "completed"] = "pending",
    job_type: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    """Return pending or completed tasks from the shared administrator inbox."""

    session = require_session_payload(request)
    if not _session_is_admin(session):
        raise HTTPException(status_code=403, detail="admin_queue_forbidden")
    service = _review_service(request)
    items = _filter_visible_queue(service.shared_admin_queue(status=status), session)
    summary = _queue_summary_from_items(items)
    canonical_job_type = canonical_resume_job_type(job_type)
    filtered_items = [
        item
        for item in items
        if not canonical_job_type
        or _queue_item_job_type(item) == canonical_job_type
    ]
    total = len(filtered_items)
    pages = (total + page_size - 1) // page_size if total else 0
    safe_page = min(page, pages) if pages else 1
    start = (safe_page - 1) * page_size
    paged_items = filtered_items[start : start + page_size]
    resume_ids = [
        str(item["resume"]["id"])
        for item in paged_items
        if isinstance(item.get("resume"), dict) and item["resume"].get("id")
    ]
    review_states = service.repository.states_for_user(current_user_id(request))
    reviewer_decisions = service.reviewer_decisions_for_resumes(resume_ids)
    return {
        "items": [
            {
                "assignment": item.get("assignment"),
                "resume": _resume_list_payload(
                    Resume.model_validate(item["resume"]),
                    review_state=review_states.get(str(item["resume"]["id"])),
                    reviewer_decisions=reviewer_decisions.get(str(item["resume"]["id"]), []),
                ),
            }
            for item in paged_items
            if isinstance(item.get("resume"), dict)
        ],
        "total": total,
        "queueTotal": summary["total"],
        "page": safe_page,
        "pageSize": page_size,
        "pages": pages,
        "jobFacets": summary["jobFacets"],
        "version": summary["version"],
    }


@router.get("/api/resume-review/queue-summary")
async def review_queue_summary(request: Request) -> dict[str, object]:
    """Return lightweight pending counts for administrator polling."""

    session = require_session_payload(request)
    if not _session_is_admin(session):
        raise HTTPException(status_code=403, detail="admin_queue_forbidden")
    summary = _review_service(request).shared_admin_queue_summary()
    scoped_job_types = allowed_job_types(session)
    if "*" in scoped_job_types:
        return summary
    allowed = {canonical_resume_job_type(job_type) for job_type in scoped_job_types}
    facets = [
        item
        for item in summary["jobFacets"]
        if canonical_resume_job_type(str(item.get("jobType") or "")) in allowed
    ]
    return {
        "total": sum(int(item.get("count") or 0) for item in facets),
        "jobFacets": facets,
        "version": summary["version"],
    }


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


def _queue_item_job_type(item: dict[str, object]) -> str:
    resume_payload = item.get("resume")
    if not isinstance(resume_payload, dict):
        return ""
    return canonical_resume_job_type(
        str(resume_payload.get("job_type") or resume_payload.get("jobType") or "")
    )


def _queue_summary_from_items(items: list[dict[str, object]]) -> dict[str, object]:
    counts: dict[str, int] = {}
    updated_at: list[str] = []
    for item in items:
        job_type = _queue_item_job_type(item)
        if job_type:
            counts[job_type] = counts.get(job_type, 0) + 1
        assignment = item.get("assignment")
        if isinstance(assignment, dict):
            value = str(assignment.get("updatedAt") or "")
            if value:
                updated_at.append(value)
    total = len(items)
    return {
        "total": total,
        "jobFacets": [
            {"jobType": job_type, "count": counts[job_type]}
            for job_type in sorted(counts)
        ],
        "version": f"{total}:{max(updated_at, default='')}",
    }


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
