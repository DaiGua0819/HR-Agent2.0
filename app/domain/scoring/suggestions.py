"""规则建议 SQLite 存储。

人工反馈生成 `rule_suggestions` 记录；采纳/拒绝会更新状态与时间戳。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.text import clean_text, clip_text
from app.db.engine import connect, run_migrations
from app.settings import load_settings


def now_iso() -> str:
    """返回 UTC ISO 时间。"""

    return datetime.now(UTC).isoformat()


@dataclass
class RuleSuggestion:
    """一条规则建议。"""

    id: str
    resume_id: str
    feedback: str
    status: str = "pending"
    payload: dict[str, Any] = field(default_factory=dict)
    job_type: str = ""
    source_summary: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    adopted_at: str = ""
    rejected_at: str = ""


class RuleSuggestionStore:
    """规则建议 SQLite 存储。"""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = (
            Path(database_path)
            if database_path
            else load_settings().resolved_database_path
        )
        run_migrations(self.database_path)

    def create(self, resume_id: str, feedback: str, *, job_type: str = "") -> RuleSuggestion:
        """根据反馈创建建议。"""

        summary = clip_text(feedback, max_length=120)
        suggestion = RuleSuggestion(
            id=str(uuid4()),
            resume_id=resume_id,
            feedback=clean_text(feedback),
            job_type=job_type,
            source_summary=summary,
            payload={
                "summary": summary,
                "proposedAction": "review_rule_threshold_or_keyword",
            },
        )
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO rule_suggestions (
                  id, resume_id, job_type, suggestion, status, source_summary,
                  payload, created_at, adopted_at, rejected_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _suggestion_params(suggestion),
            )
            connection.commit()
        return suggestion

    def list(self, *, status: str | None = None) -> list[RuleSuggestion]:
        """列出建议。"""

        sql = "SELECT * FROM rule_suggestions"
        params: tuple[Any, ...] = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY created_at DESC"
        with connect(self.database_path) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_suggestion_from_row(row) for row in rows]

    def set_status(self, suggestion_id: str, status: str) -> RuleSuggestion | None:
        """更新建议状态。"""

        current = self.get(suggestion_id)
        if current is None:
            return None
        current.status = status
        current.updated_at = now_iso()
        if status == "accepted":
            current.adopted_at = current.updated_at
        if status == "rejected":
            current.rejected_at = current.updated_at
        with connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE rule_suggestions
                SET status = ?, adopted_at = ?, rejected_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    current.status,
                    current.adopted_at or None,
                    current.rejected_at or None,
                    current.updated_at,
                    current.id,
                ),
            )
            connection.commit()
        return current

    def get(self, suggestion_id: str) -> RuleSuggestion | None:
        """读取单条建议。"""

        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM rule_suggestions WHERE id = ?",
                (suggestion_id,),
            ).fetchone()
        return _suggestion_from_row(row) if row else None

    def clear(self) -> None:
        """清空建议；仅用于临时库测试。"""

        with connect(self.database_path) as connection:
            connection.execute("DELETE FROM rule_suggestions")
            connection.commit()


GLOBAL_RULE_SUGGESTIONS = RuleSuggestionStore()
InMemoryRuleSuggestionStore = RuleSuggestionStore


def suggest_rule_adjustment(resume_id: str, feedback: str) -> dict[str, Any]:
    """根据人工反馈生成规则建议。"""

    return suggestion_to_dict(GLOBAL_RULE_SUGGESTIONS.create(resume_id, feedback))


def suggestion_to_dict(suggestion: RuleSuggestion) -> dict[str, Any]:
    """序列化规则建议。"""

    return {
        "id": suggestion.id,
        "resumeId": suggestion.resume_id,
        "feedback": suggestion.feedback,
        "status": suggestion.status,
        "payload": suggestion.payload,
        "jobType": suggestion.job_type,
        "sourceSummary": suggestion.source_summary,
        "createdAt": suggestion.created_at,
        "updatedAt": suggestion.updated_at,
        "adoptedAt": suggestion.adopted_at,
        "rejectedAt": suggestion.rejected_at,
    }


def _suggestion_params(suggestion: RuleSuggestion) -> tuple[Any, ...]:
    return (
        suggestion.id,
        suggestion.resume_id,
        suggestion.job_type,
        suggestion.feedback,
        suggestion.status,
        suggestion.source_summary,
        json.dumps(suggestion.payload, ensure_ascii=False, sort_keys=True),
        suggestion.created_at,
        suggestion.adopted_at or None,
        suggestion.rejected_at or None,
        suggestion.updated_at,
    )


def _suggestion_from_row(row: Any) -> RuleSuggestion:
    return RuleSuggestion(
        id=row["id"],
        resume_id=row["resume_id"],
        feedback=row["suggestion"],
        status=row["status"],
        payload=json.loads(row["payload"]),
        job_type=row["job_type"] or "",
        source_summary=row["source_summary"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        adopted_at=row["adopted_at"] or "",
        rejected_at=row["rejected_at"] or "",
    )
