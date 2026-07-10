"""简历 CRUD 与列表路由。

路由层只处理 HTTP 参数和错误码，具体筛选、排序、分页和写内存桩由
`domain.resume.service` 完成。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.api.routes.auth import current_user_id, require_session_payload
from app.auth.resume_scope import allowed_job_types, resume_visible_to_payload
from app.core.text import clean_text
from app.domain.resume.files import (
    preview_file_path,
    preview_media_type,
    preview_page_count,
    render_preview_image,
)
from app.domain.resume.job_types import display_resume_job_type
from app.domain.resume.models import Resume
from app.domain.resume.service import ResumeService, build_resume_service
from app.domain.resume_review.service import ResumeReviewService
from app.settings import PROJECT_ROOT

router = APIRouter(prefix="/api/resumes", tags=["resumes"])
_PDF_PREVIEW_IMAGE_CACHE_MAX = 256
_PDF_PREVIEW_IMAGE_CACHE: dict[tuple[str, str, int, int, int], tuple[bytes, str]] = {}
_PDF_PREVIEW_CACHE_VERSION = "pdf-preview-v2-scale2"


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
    school_level: Annotated[list[str] | None, Query()] = None,
    graduation_year: Annotated[list[str] | None, Query()] = None,
    read_status: str = "",
    decision: Annotated[list[str] | None, Query()] = None,
    score_min: int | None = None,
    score_max: int | None = None,
    manual_review: bool = False,
    date_from: str = "",
    date_to: str = "",
    sort: str = "updated_at",
    desc: bool = True,
) -> dict[str, object]:
    """列出简历，支持筛选、排序和分页。"""

    session = require_session_payload(request)
    user_id = current_user_id(request)
    review_service = _review_service(request)
    review_states = review_service.states_for_user(user_id) if review_service else {}
    result = _service(request).list_resumes(
        page=page,
        page_size=page_size,
        query=q,
        job_type=job_type,
        source_platform=platform or source_platform,
        owner=owner,
        education=education,
        school_level=school_level or [],
        graduation_year=graduation_year or [],
        score_min=score_min,
        score_max=score_max,
        read_status=read_status,
        decision=decision or [],
        manual_review=manual_review,
        date_from=date_from,
        date_to=date_to,
        review_states=review_states,
        allowed_job_types=allowed_job_types(session),
        sort=sort,
        descending=desc,
    )
    member_review_states = (
        review_service.member_decisions_for_resumes([item.id for item in result.items])
        if review_service and _session_is_admin(session)
        else {}
    )
    return {
        "items": [
            _resume_list_payload(
                item,
                review_state=review_states.get(item.id) if review_states else None,
                member_review_states=member_review_states.get(item.id, []),
            )
            for item in result.items
        ],
        "total": result.total,
        "page": result.page,
        "pageSize": result.page_size,
        "pages": result.pages,
        "jobFacets": result.job_facets,
    }


@router.get("/{resume_id}")
async def get_resume(resume_id: str, request: Request) -> dict[str, object]:
    """读取简历详情。"""

    resume = _service(request).get_resume(resume_id)
    _assert_resume_visible(request, resume)
    return _resume_payload(resume)


@router.get("/{resume_id}/file")
async def get_resume_file(resume_id: str, request: Request) -> FileResponse:
    """按简历 id 返回数据库记录的 PDF/图片预览文件。"""

    resume = _service(request).get_resume(resume_id)
    _assert_resume_visible(request, resume)
    path = preview_file_path(resume)
    if path is None:
        raise HTTPException(status_code=404, detail="resume_file_not_found")
    return FileResponse(
        path,
        media_type=preview_media_type(path),
        filename=path.name,
        content_disposition_type="inline",
    )


@router.get("/{resume_id}/preview-image")
async def get_resume_preview_image(
    resume_id: str,
    request: Request,
    page: Annotated[int, Query(ge=1)] = 1,
) -> Response:
    """按简历 id 返回无工具栏的简历图片预览。"""

    resume = _service(request).get_resume(resume_id)
    _assert_resume_visible(request, resume)
    path = preview_file_path(resume)
    if path is None:
        raise HTTPException(status_code=404, detail="resume_file_not_found")
    if path.suffix.lower() != ".pdf" and page != 1:
        raise HTTPException(status_code=422, detail="resume_preview_page_out_of_range")
    headers = _preview_cache_headers(path, page=page)
    if request.headers.get("if-none-match") == headers.get("ETag"):
        return Response(status_code=304, headers=headers)
    try:
        body, media_type = _render_preview_image_cached(request, resume_id, path, page=page)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(content=body, media_type=media_type, headers=headers)


@router.get("/{resume_id}/preview-pages")
async def get_resume_preview_pages(resume_id: str, request: Request) -> dict[str, object]:
    """Return per-page preview image URLs for the stored resume file."""

    resume = _service(request).get_resume(resume_id)
    _assert_resume_visible(request, resume)
    path = preview_file_path(resume)
    if path is None:
        raise HTTPException(status_code=404, detail="resume_file_not_found")
    try:
        page_count = preview_page_count(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "pageCount": page_count,
        "pages": [
            {
                "page": page_number,
                "imageUrl": f"/api/resumes/{resume.id}/preview-image?page={page_number}",
            }
            for page_number in range(1, page_count + 1)
        ],
    }

@router.get("/{resume_id}/download")
async def download_resume(resume_id: str, request: Request) -> FileResponse:
    """按简历 id 下载简历文件（PDF），文件名格式：姓名_岗位.pdf。"""

    require_session_payload(request)
    resume = _service(request).get_resume(resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    path = preview_file_path(resume)
    if path is None:
        raise HTTPException(status_code=404, detail="resume_file_not_found")
    name = (resume.name or resume.parsed_name or "").strip()
    job = (resume.job_type or resume.applied_position or "").strip()
    suffix = path.suffix.lower()
    filename = f"{name}_{job}{suffix}" if name and job else path.name
    return FileResponse(
        path,
        media_type=preview_media_type(path),
        filename=filename,
        content_disposition_type="attachment",
    )



@router.patch("/{resume_id}")
async def update_resume(
    resume_id: str,
    payload: ResumeUpdateRequest,
    request: Request,
) -> dict[str, object]:
    """编辑简历字段；写入内存桩。"""

    current = _service(request).get_resume(resume_id)
    _assert_resume_visible(request, current)
    resume = _service(request).update_resume(resume_id, payload.fields)
    if resume is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    return {"status": "updated_in_memory", "resume": _resume_payload(resume)}


@router.post("/{resume_id}/rescore")
async def rescore_resume(resume_id: str, request: Request) -> dict[str, object]:
    """重新评分并把分数写回内存桩。"""

    current = _service(request).get_resume(resume_id)
    _assert_resume_visible(request, current)
    result = _service(request).rescore_resume(resume_id)
    if result is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    return result


def _assert_resume_visible(request: Request, resume: Resume | None) -> None:
    if resume is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    session = require_session_payload(request)
    if not resume_visible_to_payload(resume, session):
        raise HTTPException(status_code=403, detail="resume_forbidden")


def _render_preview_image_cached(
    request: Request,
    resume_id: str,
    path: Path,
    *,
    page: int = 1,
) -> tuple[bytes, str]:
    if page < 1:
        raise ValueError("resume_preview_page_out_of_range")
    if path.suffix.lower() != ".pdf":
        if page != 1:
            raise ValueError("resume_preview_page_out_of_range")
        return render_preview_image(path)
    stat = path.stat()
    key = (resume_id, str(path.resolve()), stat.st_mtime_ns, stat.st_size, page)
    cached = _PDF_PREVIEW_IMAGE_CACHE.get(key)
    if cached is not None:
        return cached
    disk_path = _pdf_preview_disk_cache_path(request, resume_id, path, page=page, stat=stat)
    if disk_path.is_file():
        body = disk_path.read_bytes()
        cached = (body, "image/png")
        _remember_pdf_preview_cache(key, cached)
        return cached
    body, media_type = (
        render_preview_image(path) if page == 1 else render_preview_image(path, page=page)
    )
    _write_pdf_preview_disk_cache(disk_path, body)
    _remember_pdf_preview_cache(key, (body, media_type))
    return body, media_type


def _remember_pdf_preview_cache(
    key: tuple[str, str, int, int, int],
    value: tuple[bytes, str],
) -> None:
    if len(_PDF_PREVIEW_IMAGE_CACHE) >= _PDF_PREVIEW_IMAGE_CACHE_MAX:
        _PDF_PREVIEW_IMAGE_CACHE.pop(next(iter(_PDF_PREVIEW_IMAGE_CACHE)))
    _PDF_PREVIEW_IMAGE_CACHE[key] = value


def _preview_cache_headers(path: Path, *, page: int) -> dict[str, str]:
    stat = path.stat()
    etag = hashlib.sha256(
        f"{_PDF_PREVIEW_CACHE_VERSION}|{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{page}".encode()
    ).hexdigest()
    return {
        "Cache-Control": "private, max-age=86400",
        "ETag": f'"{etag}"',
    }


def _pdf_preview_disk_cache_path(
    request: Request,
    resume_id: str,
    path: Path,
    *,
    page: int,
    stat: Any,
) -> Path:
    cache_root = Path(
        getattr(
            request.app.state,
            "resume_preview_cache_dir",
            PROJECT_ROOT / "data" / "cache" / "resume_previews",
        )
    )
    safe_resume_id = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in resume_id
    )[:80] or "resume"
    digest = hashlib.sha256(
        f"{_PDF_PREVIEW_CACHE_VERSION}|{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{page}".encode()
    ).hexdigest()
    return cache_root / safe_resume_id / f"{digest}.png"


def _write_pdf_preview_disk_cache(path: Path, body: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(body)
        temporary.replace(path)
    except OSError:
        return


def _resume_payload(
    resume: Resume,
    review_state: object | None = None,
    member_review_states: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload = resume.model_dump()
    payload.update(_resume_display_payload(resume, review_state, member_review_states))
    return payload


def _resume_list_payload(
    resume: Resume,
    review_state: object | None = None,
    member_review_states: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload = resume.model_dump(exclude={"payload"})
    payload.update(_resume_display_payload(resume, review_state, member_review_states))
    return payload


def _resume_display_payload(
    resume: Resume,
    review_state: object | None = None,
    member_review_states: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    file_path = preview_file_path(resume)
    school = _resume_school(resume)
    school_level = _resume_school_level(resume)
    return {
        "parsedName": resume.parsed_name,
        "school": school,
        "schoolLevel": school_level,
        "educationDisplay": _education_display(resume, school, school_level),
        "displayJobType": display_resume_job_type(resume.job_type or resume.applied_position),
        "linkedSessionId": resume.linked_session_id,
        "linkedPlatform": resume.linked_platform,
        "linkedOwner": resume.linked_owner,
        "linkedPlatformConversationId": resume.linked_platform_conversation_id,
        "sourceArtifactId": resume.source_artifact_id,
        "hasFilePreview": file_path is not None,
        "filePreviewUrl": f"/api/resumes/{resume.id}/file" if file_path else "",
        "filePreviewImageUrl": (
            f"/api/resumes/{resume.id}/preview-image?page=1" if file_path else ""
        ),
        "filePreviewPagesUrl": f"/api/resumes/{resume.id}/preview-pages" if file_path else "",
        "fileDownloadUrl": f"/api/resumes/{resume.id}/download" if file_path else "",
        "reviewState": _review_state_payload(review_state),
        "memberReviewStates": member_review_states or [],
    }


def _payload_value(resume: Resume, *keys: str) -> str:
    for key in keys:
        value = resume.payload.get(key)
        if value not in (None, ""):
            return clean_text(value)
    return ""


def _resume_school(resume: Resume) -> str:
    return _payload_value(resume, "school", "college", "university")


def _resume_school_level(resume: Resume) -> str:
    return _payload_value(resume, "schoolLevel", "school_level", "schoolTier", "school_tier")


def _education_display(resume: Resume, school: str, school_level: str) -> str:
    degree = clean_text(resume.education)
    school_part = f"{school}（{school_level}）" if school and school_level else school
    parts = [part for part in [degree, school_part or school_level] if part]
    return " · ".join(parts)


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


def _session_is_admin(session: dict[str, object]) -> bool:
    roles = session.get("roles")
    return isinstance(roles, list) and bool({"super_admin", "admin"} & set(roles))
