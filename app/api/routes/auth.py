"""Local authentication routes for the control-plane UI."""

from __future__ import annotations

import hmac
import os
import secrets
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.domain.resume_review.models import LocalUser

router = APIRouter(prefix="/api/auth", tags=["auth"])
SESSION_COOKIE = "hr_agent_session"
ADMIN_VIEWS = ["dashboard", "resumes", "queue", "interviews", "automation", "rules"]
MEMBER_VIEWS = ["resumes"]


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
    permissions=[
        "resumes:read",
        "resumes:review",
    ],
    owners=["宋峰峰"],
    platforms=["boss", "job51", "zhilian"],
)
AUTH_PROFILES = {
    "admin": LocalAuthProfile(
        username="admin",
        user=LOCAL_USER,
        password_env="HR_AGENT_LOCAL_ADMIN_PASSWORD",
        development_password="admin",
    ),
    "member": LocalAuthProfile(
        username="member",
        user=MEMBER_USER,
        password_env="HR_AGENT_LOCAL_MEMBER_PASSWORD",
        development_password="member",
    ),
}


@router.get("/me")
async def me(request: Request) -> dict[str, object]:
    """Return the current session user."""

    return _user_payload(_current_user(request))


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
) -> dict[str, object]:
    """Create a local UI session."""

    profile = _authenticate(payload.username, payload.password)
    token = secrets.token_urlsafe(32)
    _session_store(request)[token] = profile.user.id
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    return _user_payload(profile.user)


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


def _current_user(request: Request) -> LocalUser:
    token = request.cookies.get(SESSION_COOKIE, "")
    user_id = _session_store(request).get(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return _user_by_id(user_id)


def _user_by_id(user_id: str) -> LocalUser:
    for profile in AUTH_PROFILES.values():
        if profile.user.id == user_id:
            return profile.user
    raise HTTPException(status_code=401, detail="not_authenticated")


def _session_store(request: Request) -> dict[str, str]:
    sessions = getattr(request.app.state, "auth_sessions", None)
    if sessions is None:
        sessions = {}
        request.app.state.auth_sessions = sessions
    return sessions


def _user_payload(user: LocalUser) -> dict[str, object]:
    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "avatarUrl": "",
        },
        "roles": user.roles,
        "permissions": user.permissions,
        "resumeScope": {
            "owners": user.owners,
            "platforms": user.platforms,
            "includeUnlinked": "super_admin" in user.roles,
        },
        "uiAccess": _ui_access(user),
    }


def _ui_access(user: LocalUser) -> dict[str, object]:
    is_admin = bool({"super_admin", "admin"} & set(user.roles))
    actions = ["resume:view", "resume:review"]
    if is_admin:
        actions.extend(["interview:invite", "automation:run"])
    return {
        "defaultView": "dashboard" if is_admin else "resumes",
        "views": ADMIN_VIEWS if is_admin else MEMBER_VIEWS,
        "actions": actions,
    }
