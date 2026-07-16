"""Models shared by the Feishu read-only recruitment bot."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BotRole = Literal["admin", "member"]
BotIntent = Literal[
    "help",
    "daily_summary",
    "resume_counts",
    "recent_resumes",
    "review_summary",
    "worker_status",
    "recent_errors",
    "unsupported",
]


@dataclass(frozen=True)
class BotEvent:
    """Normalized event emitted by `lark-cli event consume`."""

    event_id: str
    message_id: str
    sender_open_id: str
    chat_id: str
    chat_type: str
    message_type: str
    content: str
    create_time: str

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> BotEvent:
        return cls(
            event_id=str(payload.get("event_id") or "").strip(),
            message_id=str(payload.get("message_id") or payload.get("id") or "").strip(),
            sender_open_id=str(payload.get("sender_id") or "").strip(),
            chat_id=str(payload.get("chat_id") or "").strip(),
            chat_type=str(payload.get("chat_type") or "").strip().lower(),
            message_type=str(payload.get("message_type") or "").strip().lower(),
            content=str(payload.get("content") or "").strip(),
            create_time=str(payload.get("create_time") or payload.get("timestamp") or "").strip(),
        )

    def validate_required(self) -> None:
        required = {
            "event_id": self.event_id,
            "message_id": self.message_id,
            "sender_open_id": self.sender_open_id,
            "chat_id": self.chat_id,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(f"invalid_feishu_bot_event:{','.join(missing)}")


@dataclass(frozen=True)
class BotActor:
    """An explicitly authorized Feishu bot user."""

    open_id: str
    display_name: str
    role: BotRole
    job_types: tuple[str, ...]
    review_user_id: str = ""
    permissions: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def can(self, permission: str) -> bool:
        return permission in self.permissions


class BotQueryPlan(BaseModel):
    """Validated query plan emitted by Codex or the deterministic fallback."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    intent: BotIntent
    date: str = ""
    date_start: str = Field(default="", alias="dateStart")
    date_end: str = Field(default="", alias="dateEnd")
    job_types: list[str] = Field(default_factory=list, alias="jobTypes")
    owner: str = ""
    platform: str = ""
    limit: int = 10
    clarification: str = ""


@dataclass(frozen=True)
class BotQueryResult:
    """Structured facts returned by a permission-checked read-only query."""

    intent: BotIntent
    data: dict[str, object]
    coverage: dict[str, object] = field(default_factory=dict)
