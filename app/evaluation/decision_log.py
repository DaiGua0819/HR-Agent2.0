"""决策日志持久化。

Phase 7a 起，全局决策 sink 写入 SQLite `decision_logs`。测试仍可显式使用
`InMemoryDecisionSink`，调用点接口保持 `record(event)` 不变。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.db.engine import connect, run_migrations
from app.settings import load_settings


def now_iso() -> str:
    """返回 UTC ISO 时间。"""

    return datetime.now(UTC).isoformat()


@dataclass
class InMemoryDecisionSink:
    """内存决策日志 sink，供单测或局部 dry-run 使用。"""

    events: list[dict[str, Any]] = field(default_factory=list)

    def record(self, event: dict[str, Any]) -> None:
        """追加一条决策事件。"""

        self.events.append(dict(event))

    def clear(self) -> None:
        """清空测试事件。"""

        self.events.clear()


class SQLiteDecisionSink:
    """SQLite 决策日志 sink。"""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = (
            Path(database_path)
            if database_path
            else load_settings().resolved_database_path
        )
        self.events: list[dict[str, Any]] = []
        run_migrations(self.database_path)

    def record(self, event: dict[str, Any]) -> None:
        """写入一条决策事件。"""

        payload = dict(event)
        created_at = str(payload.get("createdAt") or payload.get("created_at") or now_iso())
        payload.setdefault("createdAt", created_at)
        payload.setdefault("id", str(uuid4()))
        self.events.append(payload)
        self.events = self.events[-200:]
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO decision_logs (
                  id, event_type, owner, platform, conversation_id, dry_run, payload, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["id"],
                    str(payload.get("event") or payload.get("eventType") or "decision"),
                    _optional_str(payload.get("owner")),
                    _optional_str(payload.get("platform")),
                    _optional_str(payload.get("conversationId") or payload.get("conversation_id")),
                    1 if payload.get("dryRun") or payload.get("dry_run") else 0,
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=_json_default,
                    ),
                    created_at,
                ),
            )
            connection.commit()

    def list_recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """读取最近日志。"""

        with connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT payload FROM decision_logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def clear(self) -> None:
        """清空日志；仅用于临时库测试。"""

        self.events.clear()
        with connect(self.database_path) as connection:
            connection.execute("DELETE FROM decision_logs")
            connection.commit()


GLOBAL_DECISION_SINK = SQLiteDecisionSink()


def record_decision(event: dict[str, Any]) -> None:
    """记录一次自动化决策。"""

    GLOBAL_DECISION_SINK.record(event)


def recent_decisions(limit: int = 50) -> list[dict[str, Any]]:
    """读取最近决策日志。"""

    if hasattr(GLOBAL_DECISION_SINK, "list_recent"):
        return GLOBAL_DECISION_SINK.list_recent(limit=limit)  # type: ignore[union-attr]
    return GLOBAL_DECISION_SINK.events[-limit:]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _json_default(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()  # type: ignore[attr-defined]
    if isinstance(value, Path):
        return str(value)
    return str(value)
