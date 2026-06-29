"""简历 Repository。

Phase 7a 起，默认 repository 使用新系统 SQLite 真读写，保留旧系统 payload + 索引列模式：
`payload / phone_key / job_type / match_score / updated_at`。`legacy=True` 仍可只读旧库。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.db.engine import connect, run_migrations
from app.domain.resume.models import Resume, ResumeRecord
from app.settings import AppSettings, load_settings

_BASE_COLUMNS = ["id", "payload", "phone_key", "job_type", "match_score", "updated_at"]
_BRIDGE_COLUMNS = [
    "parsed_name",
    "linked_session_id",
    "linked_platform",
    "linked_owner",
    "linked_platform_conversation_id",
    "source_artifact_id",
]


class ResumeRepository:
    """封装简历读写边界。"""

    def __init__(
        self,
        database_path: str | Path,
        *,
        read_only: bool = False,
        memory_records: list[ResumeRecord] | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.read_only = read_only
        self._memory_records = {record.id: record for record in memory_records or []}
        if not self._is_memory and not read_only:
            run_migrations(self.database_path)

    @classmethod
    def from_settings(
        cls,
        settings: AppSettings | None = None,
        *,
        legacy: bool = False,
    ) -> ResumeRepository:
        """从配置创建 repository；默认使用新系统 writable DB。"""

        resolved = settings or load_settings()
        path = (
            resolved.resolved_legacy_resume_db_path
            if legacy
            else resolved.resolved_database_path
        )
        return cls(path, read_only=legacy)

    @classmethod
    def in_memory(cls, records: list[ResumeRecord] | None = None) -> ResumeRepository:
        """测试使用的纯内存 repository。"""

        return cls(":memory:", read_only=True, memory_records=records)

    def count(self) -> int:
        """返回简历条数。"""

        if self._is_memory:
            return len(self._memory_records)
        if self.read_only and not self.database_path.exists():
            return 0
        try:
            with connect(self.database_path, read_only=self.read_only) as connection:
                row = connection.execute("SELECT COUNT(*) AS count FROM resumes").fetchone()
            return int(row["count"])
        except sqlite3.Error:
            return 0

    def iter_resumes(self, *, limit: int | None = None) -> Iterator[ResumeRecord]:
        """按更新时间倒序读取简历。"""

        if self._is_memory:
            records = sorted(
                self._memory_records.values(),
                key=lambda record: record.updated_at or "",
                reverse=True,
            )
            yield from records[:limit] if limit is not None else records
            return
        if self.read_only and not self.database_path.exists():
            return
        params: tuple[Any, ...] = ()
        suffix = " ORDER BY updated_at DESC"
        if limit is not None:
            suffix += " LIMIT ?"
            params = (limit,)
        try:
            with connect(self.database_path, read_only=self.read_only) as connection:
                sql = f"SELECT {_resume_select_columns(connection)} FROM resumes{suffix}"
                rows = connection.execute(sql, params).fetchall()
        except sqlite3.Error:
            return
        for row in rows:
            yield self._row_to_record(row)

    def list_resumes(self, *, limit: int = 20) -> list[ResumeRecord]:
        """读取前 N 条简历。"""

        return list(self.iter_resumes(limit=limit))

    def get(self, resume_id: str) -> ResumeRecord | None:
        """按主键读取单条简历。"""

        if self._is_memory:
            return self._memory_records.get(resume_id)
        if self.read_only and not self.database_path.exists():
            return None
        try:
            with connect(self.database_path, read_only=self.read_only) as connection:
                sql = (
                    f"SELECT {_resume_select_columns(connection)} "
                    "FROM resumes WHERE id = ?"
                )
                row = connection.execute(sql, (resume_id,)).fetchone()
        except sqlite3.Error:
            return None
        return self._row_to_record(row) if row else None

    def save(self, resume: Resume) -> ResumeRecord:
        """保存简历，非内存模式真实 upsert 到 SQLite。"""

        record = resume.to_record()
        if not record.updated_at:
            record = _with_updated_at(record, _now_iso())
        if self._is_memory:
            self._memory_records[record.id] = record
            return record
        self._ensure_writable()
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO resumes (
                  id, payload, phone_key, job_type, match_score, updated_at,
                  parsed_name, linked_session_id, linked_platform, linked_owner,
                  linked_platform_conversation_id, source_artifact_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  payload = excluded.payload,
                  phone_key = excluded.phone_key,
                  job_type = excluded.job_type,
                  match_score = excluded.match_score,
                  updated_at = excluded.updated_at,
                  parsed_name = excluded.parsed_name,
                  linked_session_id = excluded.linked_session_id,
                  linked_platform = excluded.linked_platform,
                  linked_owner = excluded.linked_owner,
                  linked_platform_conversation_id = excluded.linked_platform_conversation_id,
                  source_artifact_id = excluded.source_artifact_id
                """,
                _record_params(record),
            )
            connection.commit()
        return record

    def update(self, resume_id: str, fields: dict[str, Any]) -> ResumeRecord | None:
        """更新简历字段并真实落库。"""

        current = self.get(resume_id)
        if current is None:
            return None
        payload = {**current.payload, **fields}
        phone_key = fields.get("phone_key") or fields.get("phone") or current.phone_key or ""
        job_type = (
            fields.get("job_type")
            or fields.get("applied_position")
            or current.job_type
            or ""
        )
        record = ResumeRecord(
            id=resume_id,
            payload=payload,
            phone_key=str(phone_key),
            job_type=str(job_type),
            match_score=_optional_int(fields.get("match_score"), current.match_score),
            updated_at=_now_iso(),
            parsed_name=str(fields.get("parsed_name", current.parsed_name) or ""),
            linked_session_id=str(
                fields.get("linked_session_id", current.linked_session_id) or ""
            ),
            linked_platform=str(fields.get("linked_platform", current.linked_platform) or ""),
            linked_owner=str(fields.get("linked_owner", current.linked_owner) or ""),
            linked_platform_conversation_id=str(
                fields.get(
                    "linked_platform_conversation_id",
                    current.linked_platform_conversation_id,
                )
                or ""
            ),
            source_artifact_id=str(
                fields.get("source_artifact_id", current.source_artifact_id) or ""
            ),
        )
        return self.save(Resume.from_record(record))

    def update_score(self, resume_id: str, score: int) -> ResumeRecord | None:
        """更新匹配分并真实落库。"""

        return self.update(resume_id, {"match_score": score})

    @property
    def _is_memory(self) -> bool:
        return str(self.database_path) == ":memory:"

    def _ensure_writable(self) -> None:
        if self.read_only:
            raise RuntimeError("resume_repository_is_read_only")

    @staticmethod
    def _row_to_record(row: Any) -> ResumeRecord:
        payload = json.loads(row["payload"])
        if not isinstance(payload, dict):
            payload = {"value": payload}
        return ResumeRecord(
            id=row["id"],
            payload=payload,
            phone_key=row["phone_key"],
            job_type=row["job_type"],
            match_score=row["match_score"],
            updated_at=row["updated_at"],
            parsed_name=_row_value(row, "parsed_name"),
            linked_session_id=_row_value(row, "linked_session_id"),
            linked_platform=_row_value(row, "linked_platform"),
            linked_owner=_row_value(row, "linked_owner"),
            linked_platform_conversation_id=_row_value(
                row,
                "linked_platform_conversation_id",
            ),
            source_artifact_id=_row_value(row, "source_artifact_id"),
        )


def _record_params(record: ResumeRecord) -> tuple[Any, ...]:
    return (
        record.id,
        json.dumps(record.payload, ensure_ascii=False, sort_keys=True),
        record.phone_key,
        record.job_type,
        record.match_score,
        record.updated_at,
        record.parsed_name,
        record.linked_session_id,
        record.linked_platform,
        record.linked_owner,
        record.linked_platform_conversation_id,
        record.source_artifact_id,
    )


def _with_updated_at(record: ResumeRecord, updated_at: str) -> ResumeRecord:
    return ResumeRecord(
        id=record.id,
        payload=record.payload,
        phone_key=record.phone_key,
        job_type=record.job_type,
        match_score=record.match_score,
        updated_at=updated_at,
        parsed_name=record.parsed_name,
        linked_session_id=record.linked_session_id,
        linked_platform=record.linked_platform,
        linked_owner=record.linked_owner,
        linked_platform_conversation_id=record.linked_platform_conversation_id,
        source_artifact_id=record.source_artifact_id,
    )


def _resume_select_columns(connection: sqlite3.Connection) -> str:
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(resumes)")}
    columns = []
    for column in [*_BASE_COLUMNS, *_BRIDGE_COLUMNS]:
        columns.append(column if column in existing else f"NULL AS {column}")
    return ", ".join(columns)


def _row_value(row: Any, key: str) -> str:
    try:
        value = row[key]
    except (KeyError, IndexError):
        return ""
    return str(value or "")


def _optional_int(value: object, fallback: int | None) -> int | None:
    if value is None:
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
