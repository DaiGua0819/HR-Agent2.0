"""Explicit open-id access policy for the Feishu read-only bot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.text import clean_text
from app.domain.resume.job_types import canonical_resume_job_type
from app.features.feishu_bot.models import BotActor

_MEMBER_PERMISSIONS = frozenset(
    {
        "query:summary",
        "query:resumes",
        "query:reviews",
    }
)
_ADMIN_PERMISSIONS = frozenset(
    {
        *_MEMBER_PERMISSIONS,
        "query:workers",
        "query:errors",
        "query:all_jobs",
        "query:shared_queue",
    }
)


class FeishuBotAccessPolicy:
    """Load an exact open-id allow-list; names never grant access."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self._actors = self._load()

    def resolve(self, open_id: str) -> BotActor | None:
        return self._actors.get(clean_text(open_id))

    def actors(self) -> list[BotActor]:
        return list(self._actors.values())

    def _load(self) -> dict[str, BotActor]:
        if not self.config_path.is_file():
            return {}
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("invalid_feishu_bot_access_config")
        users = raw.get("users") or []
        if not isinstance(users, list):
            raise ValueError("invalid_feishu_bot_access_users")
        actors: dict[str, BotActor] = {}
        for item in users:
            if not isinstance(item, dict):
                raise ValueError("invalid_feishu_bot_access_user")
            actor = _actor_from_config(item)
            if actor is None:
                continue
            if actor.open_id in actors:
                raise ValueError(f"duplicate_feishu_bot_open_id:{actor.open_id}")
            actors[actor.open_id] = actor
        return actors


def _actor_from_config(item: dict[str, Any]) -> BotActor | None:
    if item.get("enabled", True) is False:
        return None
    open_id = clean_text(item.get("openId"))
    display_name = clean_text(item.get("displayName"))
    role = clean_text(item.get("role")).lower()
    if not open_id or not display_name or role not in {"admin", "member"}:
        raise ValueError("invalid_feishu_bot_access_user")
    runtime_control = item.get("runtimeControl") is True
    if runtime_control and role != "admin":
        raise ValueError("member_feishu_bot_runtime_control_forbidden")
    job_types = _job_types(item.get("jobTypes"), role=role)
    permissions = set(_ADMIN_PERMISSIONS if role == "admin" else _MEMBER_PERMISSIONS)
    if runtime_control:
        permissions.add("control:runtime")
    return BotActor(
        open_id=open_id,
        display_name=display_name,
        role=role,  # type: ignore[arg-type]
        job_types=job_types,
        review_user_id=clean_text(item.get("reviewUserId")),
        permissions=frozenset(permissions),
    )


def _job_types(value: object, *, role: str) -> tuple[str, ...]:
    values = value if isinstance(value, list) else [value] if value is not None else []
    result: list[str] = []
    for item in values:
        text = clean_text(item)
        if not text:
            continue
        canonical = "*" if text == "*" else canonical_resume_job_type(text)
        if canonical and canonical not in result:
            result.append(canonical)
    if role == "admin":
        return ("*",)
    if not result or "*" in result:
        raise ValueError("member_feishu_bot_job_scope_required")
    return tuple(result)
