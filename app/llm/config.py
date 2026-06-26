"""解析运行期 LLM 配置。"""

from __future__ import annotations

from dataclasses import dataclass

from app.settings import AppSettings, load_settings


@dataclass(frozen=True)
class ResolvedLLMConfig:
    """LLM 调用所需的最终配置。"""

    provider: str
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float


def get_llm_config(settings: AppSettings | None = None) -> ResolvedLLMConfig:
    """从 settings 与 env 解析 OpenAI 兼容配置。"""

    resolved = settings or load_settings()
    llm = resolved.llm
    return ResolvedLLMConfig(
        provider=llm.provider,
        api_key=llm.api_key,
        base_url=llm.base_url.rstrip("/"),
        model=llm.model_name,
        timeout_seconds=llm.timeout_seconds,
    )
