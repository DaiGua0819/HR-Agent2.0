"""面试邀请与面试中心路由。

接口覆盖旧 `/api/interview-center/*` 的核心形态：会话创建/查询、bitable 同步、出图、
反馈回填和 OAuth 结构。真实飞书/OAuth/DB 留到最后阶段。
"""

from __future__ import annotations

from html import escape
from typing import Any, TypeVar

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError

from app.api.routes.auth import require_session_payload
from app.domain.conversation.repository import ConversationRepository
from app.domain.resume.repository import ResumeRepository
from app.features.interview_center.service import InterviewCenterService
from app.features.interview_invite.service import InterviewInviteError, InterviewInviteService
from app.settings import load_settings

router = APIRouter(tags=["interview-center"])

_RequestModel = TypeVar("_RequestModel", bound=BaseModel)


class InterviewInviteRequest(BaseModel):
    """约面试入口请求。"""

    resume_id: str = Field(alias="resumeId")
    dry_run: bool = Field(default=True, alias="dryRun")
    confirm_live: bool = Field(default=False, alias="confirmLive")
    selected_session_id: str = Field(default="", alias="selectedSessionId")


class InterviewSessionCreateRequest(BaseModel):
    """面试会话创建请求。"""

    resume: dict[str, Any] = Field(default_factory=dict)
    conversation: list[dict[str, Any]] = Field(default_factory=list)
    resume_pdf_path: str | None = Field(default=None, alias="resumePdfPath")


class InterviewCenterSyncRequest(BaseModel):
    """Old interview-center calendar sync request."""

    calendar_id: str = Field(default="primary", alias="calendarId")
    auto_prepare: bool = Field(default=True, alias="autoPrepare")
    auto_prepare_limit: int = Field(default=12, alias="autoPrepareLimit")


class FeedbackBackfillRequest(BaseModel):
    """面试反馈回填请求。"""

    result: str = "feedback_received"
    feedback: str
    interviewer: str = ""


class InterviewPrepareRequest(BaseModel):
    """Old interview-center prepare request."""

    force: bool = False


class InterviewBindRequest(BaseModel):
    """Old interview-center manual resume binding request."""

    resume_id: str = Field(default="", alias="resumeId")
    prepare: bool = False


class InterviewBackfillRequest(BaseModel):
    """Old interview-center backfill request."""

    force: bool = False
    early_override: bool = Field(default=False, alias="earlyOverride")
    early_override_reason: str = Field(default="", alias="earlyOverrideReason")
    early_override_token: str = Field(default="", alias="earlyOverrideToken")


class InterviewReviewRequest(BaseModel):
    """Old interview-center human review/confirm request."""

    decision: str = "passed"
    note: str = ""


def _service(request: Request) -> InterviewCenterService:
    service = getattr(request.app.state, "interview_center_service", None)
    if service is None:
        service = InterviewCenterService()
        request.app.state.interview_center_service = service
    return service


def _invite_service(request: Request) -> InterviewInviteService:
    service = getattr(request.app.state, "interview_invite_service", None)
    if service is not None:
        return service
    settings = load_settings()
    resume_repository = getattr(request.app.state, "resume_repository", None)
    if resume_repository is None:
        resume_repository = ResumeRepository.from_settings(settings)
        request.app.state.resume_repository = resume_repository
    conversation_repository = getattr(request.app.state, "conversation_repository", None)
    if conversation_repository is None:
        conversation_repository = ConversationRepository.from_settings(settings)
        request.app.state.conversation_repository = conversation_repository
    service = InterviewInviteService(
        resume_repository=resume_repository,
        conversation_repository=conversation_repository,
        dispatcher=request.app.state.dispatcher,
    )
    request.app.state.interview_invite_service = service
    return service


def _legacy_error_response(status_code: int, exc: Exception) -> JSONResponse:
    resolved_status = int(getattr(exc, "status_code", status_code) or status_code)
    content: dict[str, object] = {"ok": False, "error": _legacy_error_message(exc)}
    payload = getattr(exc, "payload", None)
    if isinstance(payload, dict):
        content.update(payload)
    return JSONResponse(
        status_code=resolved_status,
        content=content,
    )


def _legacy_error_message(exc: Exception) -> str:
    message = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
    return _LEGACY_INTERVIEW_ERROR_MESSAGES.get(message, message)


async def _legacy_optional_body(request: Request, model: type[_RequestModel]) -> _RequestModel:
    raw_body = await _legacy_json_object(request)
    try:
        return model.model_validate(raw_body)
    except ValidationError:
        return model()


async def _legacy_json_object(request: Request) -> dict[str, Any]:
    try:
        raw_body = await request.json()
    except ValueError:
        raw_body = {}
    if not isinstance(raw_body, dict):
        return {}
    return raw_body


async def _legacy_sync_request(request: Request) -> InterviewCenterSyncRequest:
    raw_body = await _legacy_json_object(request)
    calendar_id = raw_body.get("calendarId") or "primary"
    auto_prepare_limit = raw_body.get("autoPrepareLimit") or 12
    try:
        resolved_limit = int(auto_prepare_limit)
    except (TypeError, ValueError):
        resolved_limit = 12
    return InterviewCenterSyncRequest(
        calendarId=str(calendar_id),
        autoPrepare=raw_body.get("autoPrepare") is not False,
        autoPrepareLimit=resolved_limit,
    )


_LEGACY_INTERVIEW_ERROR_MESSAGES = {
    "resume_not_found": "候选人简历不存在",
    "interview_session_not_found": "面试日程不存在",
    "interview_session_resume_required": "该日程尚未绑定候选人",
    "bound_resume_not_found": "绑定的候选人简历不存在",
    "backfill_not_available": "面试结束后 10 分钟才可读取纪要",
    "early_backfill_override_forbidden": "提前回灌未授权或授权已使用，已停止避免误读会议纪要",
    "no_valid_interview_record": "未读取到有效面试记录",
    "missing_feishu_oauth_code": "缺少 code",
}


@router.post("/api/interview/invite")
async def send_interview_invite(
    payload: InterviewInviteRequest,
    request: Request,
) -> dict[str, object]:
    """简历的“约面试”入口，默认先做平台预检。"""

    _assert_can_invite(request)
    try:
        return await _invite_service(request).invite(
            payload.resume_id,
            dry_run=payload.dry_run,
            confirm_live=payload.confirm_live,
            selected_session_id=payload.selected_session_id,
        )
    except InterviewInviteError as exc:
        status = 404 if exc.reason == "resume_not_found" else 400
        raise HTTPException(status_code=status, detail=exc.reason) from exc


def _assert_can_invite(request: Request) -> None:
    session = require_session_payload(request)
    access = session.get("uiAccess")
    actions = access.get("actions") if isinstance(access, dict) else []
    if "interview:invite" not in actions:
        raise HTTPException(status_code=403, detail="interview_invite_forbidden")


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
async def list_sessions(
    request: Request,
    startTime: int | None = None,
    endTime: int | None = None,
    status: str = "",
) -> dict[str, object]:
    """Old interview-center sessions list endpoint."""

    service = _service(request)
    now_seconds = int(service.now())
    resolved_start_time = startTime if startTime is not None else now_seconds - 86_400
    resolved_end_time = endTime if endTime is not None else now_seconds + 14 * 86_400
    sessions = await service.list_sessions_enriched(
        start_time=resolved_start_time,
        end_time=resolved_end_time,
        status=status,
    )
    return {
        "ok": True,
        "status": service.oauth().status(),
        "sessions": sessions,
        "items": sessions,
        "logs": service.store.list_logs("", 50),
    }


@router.post("/api/interview-center/sync")
async def sync_calendar(
    request: Request,
) -> dict[str, object]:
    """Old interview-center Feishu calendar sync entry point."""

    service = _service(request)
    resolved = await _legacy_sync_request(request)
    result = await service.sync_calendar(
        calendar_id=resolved.calendar_id,
        auto_prepare=resolved.auto_prepare,
        auto_prepare_limit=resolved.auto_prepare_limit,
    )
    return {"ok": True, **result, "logs": service.store.list_logs("", 30)}


@router.get("/api/interview-center/sync/status")
async def sync_calendar_status(request: Request) -> dict[str, object]:
    """Old interview-center Feishu calendar sync status entry point."""

    return {"ok": True, **_service(request).calendar_sync_status()}


@router.get("/api/interview-center/sessions/{session_id}")
async def get_session(session_id: str, request: Request) -> dict[str, object]:
    """读取面试会话详情。"""

    try:
        return _service(request).get_session(session_id)
    except KeyError as exc:
        return _legacy_error_response(404, exc)


@router.post("/api/interview-center/sessions/{session_id}/bind")
async def bind_session(
    session_id: str,
    request: Request,
    payload: InterviewBindRequest | None = None,
) -> dict[str, object]:
    """Old interview-center manual resume binding endpoint."""

    resolved = payload or InterviewBindRequest()
    try:
        result = await _service(request).bind_session(
            session_id,
            resume_id=resolved.resume_id,
            prepare=resolved.prepare,
        )
        return {"ok": True, **result, "logs": _service(request).store.list_logs("", 50)}
    except KeyError as exc:
        return _legacy_error_response(404, exc)


@router.post("/api/interview-center/sessions/{session_id}/prepare")
async def prepare_session(
    session_id: str,
    request: Request,
) -> dict[str, object]:
    """Old interview-center prepare-session endpoint."""

    resolved = await _legacy_optional_body(request, InterviewPrepareRequest)
    try:
        result = await _service(request).prepare_session(session_id, force=resolved.force)
        return {"ok": True, **result, "logs": _service(request).store.list_logs("", 50)}
    except ValueError as exc:
        return _legacy_error_response(409, exc)
    except KeyError as exc:
        return _legacy_error_response(404, exc)


@router.post("/api/interview-center/sessions/{session_id}/backfill")
async def backfill_session(
    session_id: str,
    request: Request,
) -> dict[str, object]:
    """Old interview-center backfill endpoint."""

    resolved = await _legacy_optional_body(request, InterviewBackfillRequest)
    try:
        result = await _service(request).backfill_session(
            session_id,
            force=resolved.force,
            early_override=resolved.early_override,
            early_override_reason=resolved.early_override_reason,
            early_override_token=resolved.early_override_token,
        )
        return {"ok": True, **result, "logs": _service(request).store.list_logs("", 50)}
    except ValueError as exc:
        return _legacy_error_response(409, exc)
    except KeyError as exc:
        return _legacy_error_response(404, exc)


@router.get("/api/interview-center/sessions/{session_id}/backfill-source")
async def backfill_source(session_id: str, request: Request) -> dict[str, object]:
    """Old interview-center backfill source endpoint."""

    try:
        return {"ok": True, **_service(request).backfill_source(session_id)}
    except KeyError as exc:
        return _legacy_error_response(404, exc)


@router.get("/api/interview-center/backfill/status")
async def backfill_status(request: Request) -> dict[str, object]:
    """Old interview-center backfill status endpoint."""

    return {"ok": True, **_service(request).backfill_status()}


@router.post("/api/interview-center/sessions/{session_id}/review")
async def review_session(
    session_id: str,
    request: Request,
) -> dict[str, object]:
    """Old interview-center human review endpoint."""

    resolved = await _legacy_optional_body(request, InterviewReviewRequest)
    return await _review_session_with_payload(session_id, request, resolved)


async def _review_session_with_payload(
    session_id: str,
    request: Request,
    resolved: InterviewReviewRequest,
) -> dict[str, object]:
    try:
        result = await _service(request).review_session(
            session_id,
            decision=resolved.decision,
            note=resolved.note,
        )
        return {"ok": True, **result, "logs": _service(request).store.list_logs("", 50)}
    except KeyError as exc:
        return _legacy_error_response(404, exc)


@router.post("/api/interview-center/sessions/{session_id}/confirm")
async def confirm_session(
    session_id: str,
    request: Request,
) -> dict[str, object]:
    """Old interview-center confirm endpoint; same behavior as review."""

    resolved = await _legacy_optional_body(request, InterviewReviewRequest)
    return await _review_session_with_payload(session_id, request, resolved)


@router.get("/api/interview-center/logs")
async def interview_center_logs(
    request: Request,
    sessionId: str = "",
    limit: int = 80,
) -> dict[str, object]:
    """Old interview-center logs endpoint."""

    return {"ok": True, "logs": _service(request).store.list_logs(sessionId, limit)}


@router.post("/api/interview-center/sessions/{session_id}/sync-bitable")
async def sync_bitable(session_id: str, request: Request) -> dict[str, object]:
    """将已有会话同步到飞书多维表 mock/真实接口。"""

    try:
        return await _service(request).sync_session_to_bitable(session_id)
    except KeyError as exc:
        return _legacy_error_response(404, exc)


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
        return _legacy_error_response(404, exc)


@router.get("/api/interview-center/feishu/auth-url")
async def feishu_auth_url(request: Request) -> dict[str, object]:
    """Old interview-center Feishu auth-url endpoint."""

    return _service(request).oauth().auth_url_payload()


@router.get("/api/interview-center/feishu/oauth/callback", response_model=None)
async def feishu_oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
) -> dict[str, object] | HTMLResponse:
    """Old interview-center Feishu OAuth callback endpoint."""

    try:
        result = await _service(request).oauth().handle_callback(code=code, state=state)
    except ValueError as exc:
        if not _wants_json(request):
            return _feishu_callback_failure_html(_legacy_error_message(exc), status_code=400)
        return _legacy_error_response(400, exc)
    if _wants_json(request):
        return result
    return _feishu_callback_success_html()


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "").lower()


def _feishu_callback_success_html() -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset=\"utf-8\"><title>飞书授权成功</title>"
        "<script>location.replace('/interview-center.html?feishu=connected')</script>"
        "<p>飞书授权成功，正在返回面试中心...</p>",
        headers={"Cache-Control": "no-store"},
    )


def _feishu_callback_failure_html(message: str, *, status_code: int) -> HTMLResponse:
    safe_message = escape(message, quote=False)
    return HTMLResponse(
        "<!doctype html><meta charset=\"utf-8\"><title>飞书授权失败</title>"
        f"<p>飞书授权失败：{safe_message}</p>"
        '<p><a href="/interview-center.html">返回面试中心</a></p>',
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/interview-center/feishu/status")
async def feishu_status(request: Request) -> dict[str, object]:
    """Old interview-center Feishu connection status endpoint."""

    service = _service(request)
    return {
        "ok": True,
        **service.oauth().status(),
        "calendarSync": service.calendar_sync_status(),
    }


@router.post("/api/interview-center/feishu/disconnect")
async def feishu_disconnect(request: Request) -> dict[str, object]:
    """Old interview-center Feishu disconnect endpoint."""

    return _service(request).oauth().disconnect()


@router.get("/api/interview-center/oauth/start")
async def oauth_start(request: Request) -> dict[str, object]:
    """生成 OAuth URL；真实授权联调留到最后阶段。"""

    return _service(request).oauth().authorization_url()


@router.get("/api/interview-center/oauth/callback")
async def oauth_callback(code: str, state: str, request: Request) -> dict[str, object]:
    """OAuth 回调结构占位。"""

    try:
        return await _service(request).oauth().handle_callback(code=code, state=state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.api_route(
    "/api/interview-center/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def unknown_interview_center_route(path: str) -> JSONResponse:
    """Old interview-center fallback for unknown API paths."""

    _ = path
    return JSONResponse(
        status_code=404,
        content={"ok": False, "error": "未知面试中心接口"},
    )
