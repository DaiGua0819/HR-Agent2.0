"""OpenAI 兼容 Chat Completions 客户端。

这里不绑定具体模型厂商；只依赖 `/chat/completions` 兼容接口。真实 API key、
base_url、model 均通过 `.env` 与 `config/model.yaml` 解析。
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.errors import LLMConfigurationError
from app.llm.config import ResolvedLLMConfig, get_llm_config


class LLMClient:
    """最小可测试的异步 LLM 客户端。"""

    def __init__(self, config: ResolvedLLMConfig | None = None) -> None:
        self.config = config or get_llm_config()

    async def chat_completions(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """调用 OpenAI 兼容 `/chat/completions`，返回原始 JSON。"""

        if not self.config.api_key:
            raise LLMConfigurationError("缺少 LLM API key，请设置 OPENAI_API_KEY")
        if not self.config.base_url:
            raise LLMConfigurationError("缺少 LLM base_url，请设置 OPENAI_BASE_URL")

        payload: dict[str, Any] = {
            "model": model or self.config.model,
            "messages": messages,
        }
        if tools is not None:
            payload["tools"] = tools
        if temperature is not None:
            payload["temperature"] = temperature

        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        async with httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
            headers=headers,
        ) as client:
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            return response.json()
