"""Feishu OAuth client used by the login system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.settings import FeishuConfig, load_settings

FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"


@dataclass(frozen=True)
class FeishuProfile:
    """Minimal Feishu identity required by HR Agent."""

    open_id: str
    tenant_key: str
    name: str
    union_id: str = ""
    user_id: str = ""
    email: str = ""
    avatar_url: str = ""


@dataclass
class FeishuOAuthService:
    """Build Feishu OAuth URLs and exchange callback codes for profiles."""

    config: FeishuConfig | None = None
    base_url: str = FEISHU_BASE_URL
    authorize_url: str = "https://open.feishu.cn/open-apis/authen/v1/authorize"

    def __post_init__(self) -> None:
        self.config = self.config or load_settings().feishu

    def authorization_url(self, *, state: str) -> dict[str, str]:
        """Return the Feishu authorization URL for a freshly generated state."""

        assert self.config is not None
        if not self.config.app_id or not self.config.redirect_uri:
            raise ValueError("missing_feishu_oauth_config")
        query = urlencode(
            {
                "app_id": self.config.app_id,
                "redirect_uri": self.config.redirect_uri,
                "state": state,
            }
        )
        return {"url": f"{self.authorize_url}?{query}", "state": state}

    async def exchange_code(self, code: str) -> FeishuProfile:
        """Exchange an OAuth code for the current Feishu user profile."""

        app_token = await self._app_access_token()
        user_token = await self._user_access_token(code=code, app_access_token=app_token)
        return await self._user_info(user_access_token=user_token)

    async def _app_access_token(self) -> str:
        assert self.config is not None
        if not self.config.app_id or not self.config.app_secret:
            raise ValueError("missing_feishu_app_credentials")
        payload = {"app_id": self.config.app_id, "app_secret": self.config.app_secret}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            response = await client.post("/auth/v3/app_access_token/internal", json=payload)
            response.raise_for_status()
        data = response.json()
        return _required(data, "app_access_token")

    async def _user_access_token(self, *, code: str, app_access_token: str) -> str:
        payload = {"grant_type": "authorization_code", "code": code}
        headers = {"Authorization": f"Bearer {app_access_token}"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            response = await client.post(
                "/authen/v1/oidc/access_token",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
        data = _data(response.json())
        return _required(data, "access_token")

    async def _user_info(self, *, user_access_token: str) -> FeishuProfile:
        headers = {"Authorization": f"Bearer {user_access_token}"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            response = await client.get("/authen/v1/user_info", headers=headers)
            response.raise_for_status()
        data = _data(response.json())
        return FeishuProfile(
            open_id=_required(data, "open_id"),
            union_id=str(data.get("union_id") or ""),
            user_id=str(data.get("user_id") or ""),
            tenant_key=_required(data, "tenant_key"),
            name=str(data.get("name") or data.get("en_name") or "飞书用户"),
            email=str(data.get("email") or ""),
            avatar_url=str(data.get("avatar_url") or data.get("avatar_thumb") or ""),
        )


def _data(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data") or {}
    if not isinstance(data, dict):
        raise ValueError(f"invalid_feishu_response: {response}")
    return data


def _required(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not value:
        raise ValueError(f"missing_feishu_{key}")
    return str(value)
