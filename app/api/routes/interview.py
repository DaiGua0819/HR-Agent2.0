"""面试邀请与面试中心路由。

接口覆盖旧 `/api/interview-center/*` 的核心形态：会话创建/查询、bitable 同步、出图、
反馈回填和 OAuth 结构。真实飞书/OAuth/DB 留到最后阶段。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.features.interview_center.service import InterviewCenterService

router = APIRouter(tags=["interview-center"])


class InterviewInviteRequest(BaseModel):
    """约面试入口请求。"""

    resume_id: str = Field(alias="resumeId")
    dry_run: bool = Field(default=True, alias="dryRun")


class InterviewSessionCreateRequest(BaseModel):
    """面试会话创建请求。"""

    resume: dict[str, Any] = Field(default_factory=dict)
    conversation: list[dict[str, Any]] = Field(default_factory=list)
    resume_pdf_path: str | None = Field(default=None, alias="resumePdfPath")


class FeedbackBackfillRequest(BaseModel):
    """面试反馈回填请求。"""

    result: str = "feedback_received"
    feedback: str
    interviewer: str = ""


def _service(request: Request) -> InterviewCenterService:
    service = getattr(request.app.state, "interview_center_service", None)
    if service is None:
        service = InterviewCenterService()
        request.app.state.interview_center_service = service
    return service


@router.post("/api/interview/invite")
async def send_interview_invite(
    payload: InterviewInviteRequest,
    request: Request,
) -> dict[str, object]:
    """简历的“约面试”入口；dry-run 不触发 worker 或真实外部调用。"""

    if payload.dry_run:
        return {"accepted": True, "dryRun": True, "resumeId": payload.resume_id}
    try:
        return await _service(request).create_session_from_resume(payload.resume_id, dry_run=False)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/interview-center/sessions")
async def create_session(
    payload: InterviewSessionCreateRequest,
    request: Request,
) -> dict[str, object]:
    """创建面试中心会话并跑通出题、同步和出图。"""

    return await _service(request).create_session_from_payload(
        payload.resume,
        conversation=payload.conversation,
        resume_pdf_path=payload.resume_pdf_path,
    )


@router.get("/api/interview-center/sessions")
async def list_sessions(request: Request) -> dict[str, object]:
    """列出面试会话。"""

    return {"items": _service(request).list_sessions()}


@router.get("/api/interview-center/sessions/{session_id}")
async def get_session(session_id: str, request: Request) -> dict[str, object]:
    """读取面试会话详情。"""

    try:
        return _service(request).get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/interview-center/sessions/{session_id}/sync-bitable")
async def sync_bitable(session_id: str, request: Request) -> dict[str, object]:
    """将已有会话同步到飞书多维表 mock/真实接口。"""

    try:
        return await _service(request).sync_session_to_bitable(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/interview-center/sessions/{session_id}/feedback-backfill")
async def feedback_backfill(
    session_id: str,
    payload: FeedbackBackfillRequest,
    request: Request,
) -> dict[str, object]:
    """回填面试反馈。"""

    try:
        return await _service(request).backfill_feedback(
            session_id,
            result=payload.result,
            feedback=payload.feedback,
            interviewer=payload.interviewer,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/interview-center/oauth/start")
async def oauth_start(request: Request) -> dict[str, str]:
    """生成 OAuth URL；真实授权联调留到最后阶段。"""

    return _service(request).oauth().authorization_url()


@router.get("/api/interview-center/oauth/callback")
async def oauth_callback(code: str, state: str, request: Request) -> dict[str, str]:
    """OAuth 回调结构占位。"""

    return await _service(request).oauth().handle_callback(code=code, state=state)
