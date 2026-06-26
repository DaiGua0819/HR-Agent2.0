"""飞书 OAuth 流程结构。

Phase 6 只落结构和可测 URL/状态生成；真实 OAuth 回调换 token、用户绑定留最后阶段。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode
from uuid import uuid4

from app.settings import FeishuConfig, load_settings


@dataclass
class FeishuOAuthService:
    """OAuth 授权 URL 与回调占位服务。"""

    config: FeishuConfig | None = None
    auth_base_url: str = "https://open.feishu.cn/open-apis/authen/v1/authorize"

    def __post_init__(self) -> None:
        self.config = self.config or load_settings().feishu

    def authorization_url(self, *, state: str | None = None) -> dict[str, str]:
        """生成飞书授权 URL。"""

        assert self.config is not None
        oauth_state = state or str(uuid4())
        query = urlencode(
            {
                "app_id": self.config.app_id,
                "redirect_uri": self.config.redirect_uri,
                "state": oauth_state,
            }
        )
        return {"url": f"{self.auth_base_url}?{query}", "state": oauth_state}

    async def handle_callback(self, *, code: str, state: str) -> dict[str, str]:
        """OAuth 回调占位；真实 code 换 token 留到最后阶段。"""

        return {
            "status": "mocked",
            "code": code,
            "state": state,
            "message": "real_oauth_exchange_deferred",
        }
