"""邮箱简历导入路由。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.domain.email_import.service import GLOBAL_EMAIL_IMPORT_SERVICE, EmailImportService

router = APIRouter(prefix="/api/email", tags=["email-import"])


class AutoEmailRequest(BaseModel):
    """邮箱自动检测开关请求。"""

    enabled: bool


def _service(request: Request) -> EmailImportService:
    service = getattr(request.app.state, "email_import_service", None)
    if service is None:
        service = GLOBAL_EMAIL_IMPORT_SERVICE
        request.app.state.email_import_service = service
    return service


@router.post("/resumes/import")
async def import_email_resumes(request: Request) -> dict[str, object]:
    """触发邮箱附件简历导入。"""

    return await _service(request).import_resumes()


@router.get("/resumes/auto-status")
async def auto_status(request: Request) -> dict[str, bool]:
    """读取邮箱自动检测开关。"""

    return _service(request).auto_status()


@router.post("/resumes/auto")
async def set_auto_status(payload: AutoEmailRequest, request: Request) -> dict[str, bool]:
    """切换邮箱自动检测开关。"""

    return _service(request).set_auto_enabled(payload.enabled)
