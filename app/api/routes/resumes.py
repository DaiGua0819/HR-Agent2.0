"""简历 CRUD 与列表路由。

路由层只处理 HTTP 参数和错误码，具体筛选、排序、分页和写内存桩由
`domain.resume.service` 完成。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.routes.auth import LOCAL_USER
from app.domain.resume.models import Resume
from app.domain.resume.service import ResumeService, build_resume_service
from app.domain.resume_review.service import ResumeReviewService

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


class ResumeUpdateRequest(BaseModel):
    """简历编辑请求。"""

    fields: dict[str, Any] = Field(default_factory=dict)


def _service(request: Request) -> ResumeService:
    service = getattr(request.app.state, "resume_service", None)
    if service is None:
        service = build_resume_service()
        request.app.state.resume_service = service
    return service


def _review_service(request: Request) -> ResumeReviewService | None:
    return getattr(request.app.state, "resume_review_service", None)


@router.get("")
async def list_resumes(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    q: str = "",
    job_type: str = "",
    source_platform: str = "",
    owner: str = "",
    platform: str = "",
    education: str = "",
    read_status: str = "",
    decision: str = "",
    score_min: int | None = None,
    score_max: int | None = None,
    sort: str = "updated_at",
    desc: bool = True,
) -> dict[str, object]:
    """列出简历，支持筛选、排序和分页。"""

    review_service = _review_service(request)
    review_states = review_service.states_for_user(LOCAL_USER.id) if review_service else {}
    result = _service(request).list_resumes(
        page=page,
        page_size=page_size,
        query=q,
        job_type=job_type,
        source_platform=platform or source_platform,
        owner=owner,
        education=education,
        score_min=score_min,
        score_max=score_max,
        read_status=read_status,
        decision=decision,
        review_states=review_states,
        sort=sort,
        descending=desc,
    )
    return {
        "items": [
            _resume_payload(
                item,
                review_state=review_states.get(item.id) if review_states else None,
            )
            for item in result.items
        ],
        "total": result.total,
        "page": result.page,
        "pageSize": result.page_size,
        "pages": result.pages,
    }


@router.get("/{resume_id}")
async def get_resume(resume_id: str, request: Request) -> dict[str, object]:
    """读取简历详情。"""

    resume = _service(request).get_resume(resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    return _resume_payload(resume)


@router.patch("/{resume_id}")
async def update_resume(
    resume_id: str,
    payload: ResumeUpdateRequest,
    request: Request,
) -> dict[str, object]:
    """编辑简历字段；写入内存桩。"""

    resume = _service(request).update_resume(resume_id, payload.fields)
    if resume is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    return {"status": "updated_in_memory", "resume": _resume_payload(resume)}


@router.post("/{resume_id}/rescore")
async def rescore_resume(resume_id: str, request: Request) -> dict[str, object]:
    """重新评分并把分数写回内存桩。"""

    result = _service(request).rescore_resume(resume_id)
    if result is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    return result


def _resume_payload(resume: Resume, review_state: object | None = None) -> dict[str, object]:
    payload = resume.model_dump()
    payload.update(
        {
            "parsedName": resume.parsed_name,
            "linkedSessionId": resume.linked_session_id,
            "linkedPlatform": resume.linked_platform,
            "linkedOwner": resume.linked_owner,
            "linkedPlatformConversationId": resume.linked_platform_conversation_id,
            "sourceArtifactId": resume.source_artifact_id,
            "reviewState": _review_state_payload(review_state),
        }
    )
    return payload


def _review_state_payload(state: object | None) -> dict[str, object]:
    if state is None:
        return {
            "readStatus": "unread",
            "decision": "undecided",
            "reasonTags": [],
            "note": "",
        }
    return {
        "id": getattr(state, "id", ""),
        "readStatus": getattr(state, "read_status", "unread"),
        "decision": getattr(state, "decision", "undecided"),
        "reasonTags": getattr(state, "reason_tags", []),
        "note": getattr(state, "note", ""),
        "assignedTo": getattr(state, "assigned_to", ""),
        "viewedAt": getattr(state, "viewed_at", ""),
    }
