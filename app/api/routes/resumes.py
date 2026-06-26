"""简历 CRUD 与列表路由。

路由层只处理 HTTP 参数和错误码，具体筛选、排序、分页和写内存桩由
`domain.resume.service` 完成。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.domain.resume.service import ResumeService, build_resume_service

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


@router.get("")
async def list_resumes(
    request: Request,
    page: int = 1,
    page_size: int = 20,
    q: str = "",
    job_type: str = "",
    source_platform: str = "",
    sort: str = "updated_at",
    desc: bool = True,
) -> dict[str, object]:
    """列出简历，支持筛选、排序和分页。"""

    result = _service(request).list_resumes(
        page=page,
        page_size=page_size,
        query=q,
        job_type=job_type,
        source_platform=source_platform,
        sort=sort,
        descending=desc,
    )
    return {
        "items": [item.model_dump() for item in result.items],
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
    return resume.model_dump()


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
    return {"status": "updated_in_memory", "resume": resume.model_dump()}


@router.post("/{resume_id}/rescore")
async def rescore_resume(resume_id: str, request: Request) -> dict[str, object]:
    """重新评分并把分数写回内存桩。"""

    result = _service(request).rescore_resume(resume_id)
    if result is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    return result
