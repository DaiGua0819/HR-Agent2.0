"""Store-backed Feishu OAuth flow for the interview center."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode
from uuid import uuid4

import httpx

from app.features.interview_center.feishu.routes import DEFAULT_BITABLE_TABLE_ROUTES
from app.settings import FeishuConfig, load_settings

DEFAULT_FEISHU_OAUTH_SCOPES = " ".join(
    [
        "offline_access",
        "auth:user.id:read",
        "calendar:calendar:readonly",
        "calendar:calendar.event:read",
        "docx:document",
        "bitable:app",
        "drive:drive",
        "drive:drive:readonly",
        "drive:file:upload",
        "vc:meeting.meetingevent:read",
        "vc:meeting.search:read",
        "vc:record:readonly",
        "vc:note:read",
        "minutes:minutes:readonly",
        "minutes:minutes.artifacts:read",
        "minutes:minutes.search:read",
        "minutes:minutes.transcript:export",
    ]
)


class FeishuOAuthHttpClientProtocol(Protocol):
    """HTTP boundary for Feishu OAuth operations."""

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange an OAuth code for a token payload."""

    async def user_info(self, access_token: str) -> dict[str, Any]:
        """Read user info for a user access token."""


@dataclass
class FeishuOAuthHttpClient:
    """Real Feishu OAuth HTTP client."""

    config: FeishuConfig | None = None
    base_url: str = "https://open.feishu.cn/open-apis"

    def __post_init__(self) -> None:
        self.config = self.config or load_settings().feishu

    async def exchange_code(self, code: str) -> dict[str, Any]:
        app_token = await self._app_access_token()
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            response = await client.post(
                "/authen/v1/access_token",
                headers={"Authorization": f"Bearer {app_token}"},
                json={"grant_type": "authorization_code", "code": code},
            )
            response.raise_for_status()
        return dict(response.json().get("data") or {})

    async def user_info(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            response = await client.get(
                "/authen/v1/user_info",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
        return dict(response.json().get("data") or {})

    async def _app_access_token(self) -> str:
        assert self.config is not None
        if not self.config.app_id or not self.config.app_secret:
            raise ValueError("missing_feishu_app_credentials")
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            response = await client.post(
                "/auth/v3/app_access_token/internal",
                json={"app_id": self.config.app_id, "app_secret": self.config.app_secret},
            )
            response.raise_for_status()
        token = response.json().get("app_access_token")
        if not token:
            raise ValueError("missing_feishu_app_access_token")
        return str(token)


@dataclass
class FeishuOAuthService:
    """Feishu OAuth URL, callback, status, and disconnect service."""

    store: Any | None = None
    http_client: FeishuOAuthHttpClientProtocol | None = None
    config: FeishuConfig | None = None
    auth_base_url: str = "https://open.feishu.cn/open-apis/authen/v1/authorize"

    def __post_init__(self) -> None:
        self.config = self.config or load_settings().feishu
        self.http_client = self.http_client or FeishuOAuthHttpClient(self.config)

    def authorization_url(self, *, state: str | None = None) -> dict[str, str]:
        """Build a Feishu authorization URL."""

        assert self.config is not None
        oauth_state = state or str(uuid4())
        query = urlencode(
            {
                "app_id": self.config.app_id,
                "redirect_uri": self.config.redirect_uri,
                "scope": DEFAULT_FEISHU_OAUTH_SCOPES,
                "state": oauth_state,
            }
        )
        return {"url": f"{self.auth_base_url}?{query}", "state": oauth_state}

    def auth_url_payload(self, *, state: str | None = None) -> dict[str, Any]:
        """Return old-compatible auth-url response payload."""

        assert self.config is not None
        auth = self.authorization_url(state=state)
        return {
            "ok": True,
            "configured": bool(self.config.app_id and self.config.app_secret),
            "redirectUri": self.config.redirect_uri,
            "authUrl": auth["url"],
            "state": auth["state"],
        }

    async def handle_callback(self, *, code: str, state: str) -> dict[str, Any]:
        """Exchange OAuth code, persist token, and return connection status."""

        if not code:
            raise ValueError("missing_feishu_oauth_code")
        assert self.http_client is not None
        raw = await self.http_client.exchange_code(code)
        access_token = str(raw.get("access_token") or raw.get("accessToken") or "")
        if not access_token:
            raise ValueError("missing_feishu_user_access_token")
        user_info = await self.http_client.user_info(access_token)
        token = {
            "accessToken": access_token,
            "refreshToken": raw.get("refresh_token") or raw.get("refreshToken") or "",
            "expiresAt": _expires_at(raw.get("expires_in") or raw.get("expire")),
            "refreshExpiresAt": _expires_at(raw.get("refresh_expires_in"), default=0),
            "userInfo": user_info,
            "updatedAt": int(time.time() * 1000),
            "state": state,
        }
        if self.store is not None:
            self.store.save_token(token)
        return {
            "ok": True,
            "connected": True,
            "userInfo": user_info,
            "expiresAt": token["expiresAt"],
        }

    def status(self) -> dict[str, Any]:
        """Return old-compatible Feishu status."""

        assert self.config is not None
        token = self.store.get_token() if self.store is not None else None
        return {
            "configured": bool(self.config.app_id and self.config.app_secret),
            "connected": bool(token and token.get("accessToken")),
            "userInfo": token.get("userInfo") if token else None,
            "expiresAt": token.get("expiresAt") if token else 0,
            "bitableRoutes": [
                {
                    "tableId": route.table_id,
                    "tableName": route.table_name,
                    "keywords": list(route.keywords),
                }
                for route in DEFAULT_BITABLE_TABLE_ROUTES
            ],
        }

    def disconnect(self) -> dict[str, Any]:
        """Clear the stored user token."""

        if self.store is not None:
            self.store.clear_token()
        return {"ok": True, "message": "已断开飞书日历授权"}


def _expires_at(value: Any, *, default: int | None = None) -> int:
    if value in (None, ""):
        return int(default or 0)
    seconds = max(0, int(value) - 120)
    return int(time.time() * 1000) + seconds * 1000
