"""飞书鉴权与 token 客户端。

本文件只封装 OAuth/token HTTP 边界，不在领域服务里散落飞书细节。真实调用需要
运行时提供 env 中的 appId/appSecret；测试通过 mock bitable 客户端绕开外部网络。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.settings import FeishuConfig, load_settings

FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"


class FeishuTokenProvider(Protocol):
    """提供 tenant access token 的协议。"""

    async def tenant_access_token(self) -> str:
        """返回 tenant access token。"""


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
