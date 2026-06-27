"""集中加载 .env 与 config/*.yaml 的应用配置。

该模块是新系统去硬编码的边界：端口、DB 路径、LLM、worker 与账号顺序都从
`.env` 或 `config/` 进入。代码可以解析运行期绝对路径，但仓库文件不写机器绝对路径。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import Platform

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"


class WorkerConfig(BaseModel):
    """单个 worker 的进程、浏览器与平台账号配置。"""

    owner: str
    port: int
    profile_dir: Path
    cdp_port: int
    accounts: list[Platform]

    @property
    def resolved_profile_dir(self) -> Path:
        """把 config 中的 profile 相对路径解析到 data/ 下。"""

        if self.profile_dir.is_absolute():
            return self.profile_dir
        return PROJECT_ROOT / "data" / self.profile_dir


class AccountOpenOrder(BaseModel):
    """控制面串行派发平台账号的顺序。"""

    platform: Platform
    owner: str


class LLMConfig(BaseModel):
    """OpenAI 兼容模型配置；真实 key 与 base_url 在运行时由 env 提供。"""

    provider: str = "openai-compatible"
    api_key_env: str = "OPENAI_API_KEY"
    base_url_env: str = "OPENAI_BASE_URL"
    model_env: str = "OPENAI_MODEL"
    default_model: str = "gpt-5.5"
    timeout_seconds: float = 60

    @property
    def api_key(self) -> str:
        return os.getenv(self.api_key_env, "")

    @property
    def base_url(self) -> str:
        return os.getenv(self.base_url_env, "")

    @property
    def model_name(self) -> str:
        return os.getenv(self.model_env, self.default_model)


class FeishuConfig(BaseModel):
    """飞书配置只保存 env 变量名，真实密钥运行时从环境读取。"""

    app_id_env: str = "FEISHU_APP_ID"
    app_secret_env: str = "FEISHU_APP_SECRET"
    redirect_uri_env: str = "FEISHU_REDIRECT_URI"
    bitable_app_token_env: str = "FEISHU_BITABLE_APP_TOKEN"
    candidate_table_id_env: str = "FEISHU_CANDIDATE_TABLE_ID"
    interview_table_id_env: str = "FEISHU_INTERVIEW_TABLE_ID"

    @property
    def app_id(self) -> str:
        return os.getenv(self.app_id_env, "")

    @property
    def app_secret(self) -> str:
        return os.getenv(self.app_secret_env, "")

    @property
    def redirect_uri(self) -> str:
        return os.getenv(self.redirect_uri_env, "")

    @property
    def bitable_app_token(self) -> str:
        return os.getenv(self.bitable_app_token_env, "")

    @property
    def candidate_table_id(self) -> str:
        return os.getenv(self.candidate_table_id_env, "interview_candidates")

    @property
    def interview_table_id(self) -> str:
        return os.getenv(self.interview_table_id_env, "interview_sessions")


class AppSettings(BaseSettings):
    """应用总配置。

    BaseSettings 负责读取 `.env`，`load_settings()` 再叠加 YAML 中的结构化配置。
    """

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "hr-agent"
    environment: str = Field(default="development", validation_alias="APP_ENV")
    control_plane_host: str = Field(default="127.0.0.1", validation_alias="CONTROL_PLANE_HOST")
    control_plane_port: int = Field(default=8080, validation_alias="CONTROL_PLANE_PORT")
    dry_run: bool = Field(default=True, validation_alias="DRY_RUN")
    interaction_enabled: bool = Field(default=True, validation_alias="INTERACTION_ENABLED")
    interaction_profile: str = Field(default="normal", validation_alias="INTERACTION_PROFILE")
    database_path: Path = Field(
        default=Path("data/resumes.sqlite"),
        validation_alias="DATABASE_PATH",
    )
    legacy_resume_db_path: Path = Field(
        default=Path("../patchwork-recruit-gpt/data/resumes.sqlite"),
        validation_alias="LEGACY_RESUME_DB_PATH",
    )
    workers: list[WorkerConfig] = Field(default_factory=list)
    open_order: list[AccountOpenOrder] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)

    def resolve_path(self, value: Path) -> Path:
        """解析项目内相对路径；env 中的绝对路径保持原样。"""

        if value.is_absolute():
            return value
        return PROJECT_ROOT / value

    @property
    def resolved_database_path(self) -> Path:
        return self.resolve_path(self.database_path)

    @property
    def resolved_legacy_resume_db_path(self) -> Path:
        return self.resolve_path(self.legacy_resume_db_path)

    def worker_for_owner(self, owner: str) -> WorkerConfig:
        """按负责人查找 worker 配置。"""

        for worker in self.workers:
            if worker.owner == owner:
                return worker
        raise ValueError(f"未找到负责人对应的 worker: {owner}")


def _load_yaml_config(filename: str) -> dict[str, Any]:
    path = CONFIG_DIR / filename
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"配置文件必须是 YAML 对象: {path}")
    return data


@lru_cache(maxsize=1)
def load_settings() -> AppSettings:
    """加载并缓存应用配置。"""

    settings = AppSettings()
    accounts_config = _load_yaml_config("accounts.yaml")
    model_config = _load_yaml_config("model.yaml")

    updates: dict[str, Any] = {}
    if accounts_config:
        updates["workers"] = [
            WorkerConfig.model_validate(item) for item in accounts_config["workers"]
        ]
        updates["open_order"] = [
            AccountOpenOrder.model_validate(item) for item in accounts_config["open_order"]
        ]
    if model_config.get("llm"):
        updates["llm"] = LLMConfig.model_validate(model_config["llm"])

    if updates:
        settings = settings.model_copy(update=updates)
    return settings
