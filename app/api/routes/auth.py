"""Authentication routes for local development and Feishu OAuth login."""

from __future__ import annotations

import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.auth.access import feishu_payload, user_payload, validate_company
from app.auth.feishu_oauth import FeishuOAuthService
from app.domain.resume_review.models import LocalUser
from app.settings import PROJECT_ROOT

router = APIRouter(prefix="/api/auth", tags=["auth"])
SESSION_COOKIE = "hr_agent_session"


class LoginRequest(BaseModel):
    """Local login payload used before Feishu OAuth is enabled."""

    username: str
    password: str


@dataclass(frozen=True)
class LocalAuthProfile:
    """Development login profile with env-overridable password."""

    username: str
    user: LocalUser
    password_env: str
    development_password: str


LOCAL_USER = LocalUser(
    id="local-admin",
    name="本地管理员",
    roles=["super_admin"],
    permissions=[
        "resumes:read",
        "resumes:write",
        "resumes:review",
        "resumes:assign",
        "automation:run",
        "monitoring:read",
        "interview:read",
    ],
    owners=["和新红", "宋峰峰"],
    platforms=["boss", "job51", "zhilian"],
)
MEMBER_USER = LocalUser(
    id="local-member",
    name="普通成员",
    roles=["member"],
    permissions=["resumes:read", "resumes:review"],
    owners=["宋峰峰"],
    platforms=["boss", "job51", "zhilian"],
)
AUTH_PROFILES = {
    "admin": LocalAuthProfile("admin", LOCAL_USER, "HR_AGENT_LOCAL_ADMIN_PASSWORD", "admin"),
    "member": LocalAuthProfile("member", MEMBER_USER, "HR_AGENT_LOCAL_MEMBER_PASSWORD", "member"),
}


@router.get("/me")
async def me(request: Request) -> dict[str, object]:
    """Return the current session payload."""

    payload = _session_payload(request)
    if payload is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return payload


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
) -> dict[str, object]:
    """Create a local development UI session."""

    profile = _authenticate(payload.username, payload.password)
    session_payload = user_payload(profile.user)
    _set_session(request, response, session_payload)
    return session_payload


@router.get("/feishu/start")
async def feishu_start(request: Request) -> RedirectResponse:
    """Redirect the user to Feishu OAuth authorization."""

    state = secrets.token_urlsafe(24)
    _oauth_state_store(request)[state] = True
    service = _feishu_service(request)
    try:
        target = service.authorization_url(state=state)["url"]
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return RedirectResponse(target)


@router.get("/feishu/callback")
async def feishu_callback(
    code: str,
    state: str,
    request: Request,
) -> RedirectResponse:
    """Handle Feishu OAuth callback and create a role-scoped session."""

    if not _oauth_state_store(request).pop(state, None):
        raise HTTPException(status_code=400, detail="invalid_oauth_state")
    try:
        profile = await _feishu_service(request).exchange_code(code)
        validate_company(profile)
        session_payload = feishu_payload(profile)
        _write_feishu_login_diagnostics(request, session_payload)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    redirect = RedirectResponse("/index.html")
    _set_session(request, redirect, session_payload)
    return redirect


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, str]:
    """Clear the current local session."""

    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        _session_store(request).pop(token, None)
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "ok"}


def _authenticate(username: str, password: str) -> LocalAuthProfile:
    profile = AUTH_PROFILES.get(username.strip().lower())
    if profile is None:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    expected = os.getenv(profile.password_env, profile.development_password)
    if not hmac.compare_digest(password, expected):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    return profile


def require_session_payload(request: Request) -> dict[str, object]:
    """Return the authenticated session payload or reject the request."""

    payload = _session_payload(request)
    if payload is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return payload


def current_user_id(request: Request) -> str:
    """Return the stable user id from the authenticated session."""

    payload = require_session_payload(request)
    user = payload.get("user")
    if not isinstance(user, dict) or not user.get("id"):
        raise HTTPException(status_code=401, detail="invalid_session")
    return str(user["id"])


def _set_session(request: Request, response: Response, payload: dict[str, object]) -> None:
    token = secrets.token_urlsafe(32)
    _session_store(request)[token] = payload
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 12,
    )


def _session_payload(request: Request) -> dict[str, object] | None:
    return _session_store(request).get(request.cookies.get(SESSION_COOKIE, ""))


def _session_store(request: Request) -> dict[str, dict[str, object]]:
    sessions = getattr(request.app.state, "auth_sessions", None)
    if sessions is None:
        sessions = {}
        request.app.state.auth_sessions = sessions
    return sessions


def _oauth_state_store(request: Request) -> dict[str, bool]:
    states = getattr(request.app.state, "oauth_states", None)
    if states is None:
        states = {}
        request.app.state.oauth_states = states
    return states


def _feishu_service(request: Request) -> FeishuOAuthService:
    service = getattr(request.app.state, "feishu_oauth_service", None)
    if service is None:
        service = FeishuOAuthService()
        request.app.state.feishu_oauth_service = service
    return service


def _write_feishu_login_diagnostics(
    request: Request,
    payload: dict[str, object],
) -> None:
    """Persist non-token Feishu identity fields for first-run allow-list setup."""

    path = getattr(request.app.state, "feishu_login_diagnostics_path", None)
    diagnostics_path = (
        Path(path)
        if path
        else PROJECT_ROOT / "data" / "diagnostics" / "last_feishu_login.json"
    )
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    feishu = payload.get("feishu", {})
    user = payload.get("user", {})
    safe_payload = {
        "loggedAt": datetime.now(UTC).isoformat(),
        "user": user,
        "roles": payload.get("roles", []),
        "feishu": feishu,
    }
    diagnostics_path.write_text(
        json.dumps(safe_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
