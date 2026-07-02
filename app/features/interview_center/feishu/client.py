"""飞书鉴权与 token 客户端。

本文件只封装 OAuth/token HTTP 边界，不在领域服务里散落飞书细节。真实调用需要
运行时提供 env 中的 appId/appSecret；测试通过 mock bitable 客户端绕开外部网络。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.features.interview_center.store import InterviewStoreProtocol
from app.settings import FeishuConfig, load_settings

FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"


class FeishuTokenProvider(Protocol):
    """提供 tenant access token 的协议。"""

    async def tenant_access_token(self) -> str:
        """返回 tenant access token。"""


class FeishuUserTokenProvider(Protocol):
    """Provides a Feishu user access token for OAuth-scoped APIs."""

    async def user_access_token(self) -> str:
        """Return a valid user access token, or an empty string when disconnected."""


class FeishuTokenRefreshClient(Protocol):
    """Refreshes a Feishu OAuth user token."""

    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh a user access token."""


@dataclass
class FeishuAuthClient:
    """飞书鉴权客户端。"""

    config: FeishuConfig | None = None
    base_url: str = FEISHU_BASE_URL

    def __post_init__(self) -> None:
        self.config = self.config or load_settings().feishu

    async def tenant_access_token(self) -> str:
        """获取 tenant access token；缺配置时明确报错，避免隐式使用假密钥。"""

        assert self.config is not None
        if not self.config.app_id or not self.config.app_secret:
            raise ValueError("missing_feishu_app_credentials")
        payload = {"app_id": self.config.app_id, "app_secret": self.config.app_secret}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            response = await client.post("/auth/v3/tenant_access_token/internal", json=payload)
            response.raise_for_status()
        data = response.json()
        token = data.get("tenant_access_token")
        if not token:
            raise ValueError(f"missing_tenant_access_token: {data}")
        return str(token)

    async def authorized_headers(self) -> dict[str, str]:
        """生成飞书 API 授权头。"""

        return {"Authorization": f"Bearer {await self.tenant_access_token()}"}


    async def app_access_token(self) -> str:
        """Return an app access token for OAuth user-token operations."""

        assert self.config is not None
        if not self.config.app_id or not self.config.app_secret:
            raise ValueError("missing_feishu_app_credentials")
        payload = {"app_id": self.config.app_id, "app_secret": self.config.app_secret}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            response = await client.post("/auth/v3/app_access_token/internal", json=payload)
            response.raise_for_status()
        data = response.json()
        token = data.get("app_access_token")
        if not token:
            raise ValueError(f"missing_app_access_token: {data}")
        return str(token)

    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh an OAuth user access token."""

        app_token = await self.app_access_token()
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            response = await client.post(
                "/authen/v1/refresh_access_token",
                headers={"Authorization": f"Bearer {app_token}"},
                json={"grant_type": "refresh_token", "refresh_token": refresh_token},
            )
            response.raise_for_status()
        return dict(response.json().get("data") or {})


@dataclass
class FeishuStoredUserTokenProvider:
    """Store-backed user token provider with refresh support."""

    store: InterviewStoreProtocol
    refresh_client: FeishuTokenRefreshClient | None = None
    now_ms: Any | None = None

    def __post_init__(self) -> None:
        self.refresh_client = self.refresh_client or FeishuAuthClient()
        self.now_ms = self.now_ms or (lambda: int(time.time() * 1000))

    async def user_access_token(self) -> str:
        token = self.store.get_token()
        if not token or not token.get("accessToken"):
            return ""
        expires_at = int(token.get("expiresAt") or 0)
        refresh_token = str(token.get("refreshToken") or "")
        assert self.now_ms is not None
        if expires_at and expires_at <= int(self.now_ms()) + 60_000 and refresh_token:
            assert self.refresh_client is not None
            raw = await self.refresh_client.refresh_token(refresh_token)
            refreshed = {
                "accessToken": raw.get("access_token") or raw.get("accessToken") or "",
                "refreshToken": (
                    raw.get("refresh_token") or raw.get("refreshToken") or refresh_token
                ),
                "expiresAt": _expires_at(raw.get("expires_in") or raw.get("expire")),
                "refreshExpiresAt": _expires_at(
                    raw.get("refresh_expires_in"),
                    default=token.get("refreshExpiresAt") or 0,
                ),
                "userInfo": token.get("userInfo"),
                "updatedAt": int(time.time() * 1000),
            }
            self.store.save_token(refreshed)
            return str(refreshed["accessToken"])
        return str(token.get("accessToken") or "")


class StaticTokenProvider:
    """测试和本地 dry-run 使用的固定 token provider。"""

    def __init__(self, token: str = "mock-token") -> None:
        self.token = token

    async def tenant_access_token(self) -> str:
        return self.token


def compact_feishu_response(data: dict[str, Any]) -> dict[str, Any]:
    """规整飞书响应，保留 code/msg/data 三段。"""

    return {
        "code": data.get("code", 0),
        "msg": data.get("msg", ""),
        "data": data.get("data", {}),
    }


def _expires_at(value: Any, *, default: Any = 0) -> int:
    if value in (None, ""):
        return int(default or 0)
    seconds = max(0, int(value) - 120)
    return int(time.time() * 1000) + seconds * 1000
