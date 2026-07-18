"""简历审阅状态 SQLite repository。"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.db.engine import connect, run_migrations
from app.domain.resume_review.models import ReviewAssignment, ReviewState
from app.settings import load_settings


class ResumeReviewRepository:
    """读写审阅状态、审阅事件和合适队列。"""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = (
            Path(database_path) if database_path else load_settings().resolved_database_path
        )
        run_migrations(self.database_path)

    def get_state(self, resume_id: str, user_id: str) -> ReviewState | None:
        """读取某用户对某简历的审阅状态。"""

        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM resume_review_states
                WHERE resume_id = ? AND user_id = ?
                """,
                (resume_id, user_id),
            ).fetchone()
        return _state_from_row(row) if row else None

    def states_for_user(self, user_id: str) -> dict[str, ReviewState]:
        """读取用户所有审阅状态，按 resume_id 建索引。"""

        with connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM resume_review_states WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return {row["resume_id"]: _state_from_row(row) for row in rows}

    def states_for_resumes(self, resume_ids: Iterable[str]) -> dict[str, list[ReviewState]]:
        """读取一批简历的非空审阅判断，按 resume_id 分组。"""

        ids = sorted({str(resume_id) for resume_id in resume_ids if str(resume_id)})
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        with connect(self.database_path) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM resume_review_states
                WHERE resume_id IN ({placeholders}) AND decision != 'undecided'
                ORDER BY updated_at DESC
                """,
                tuple(ids),
            ).fetchall()
        grouped: dict[str, list[ReviewState]] = {resume_id: [] for resume_id in ids}
        for row in rows:
            state = _state_from_row(row)
            grouped.setdefault(state.resume_id, []).append(state)
        return grouped

    def upsert_state(
        self,
        *,
        resume_id: str,
        user_id: str,
        user_name: str | None = None,
        read_status: str | None = None,
        decision: str | None = None,
        reason_tags: Iterable[str] | None = None,
        note: str | None = None,
        assigned_to: str | None = None,
        viewed_at: str | None = None,
        decision_at: str | None = None,
        pushed_at: str | None = None,
    ) -> ReviewState:
        """更新审阅状态，未存在时创建。"""

        current = self.get_state(resume_id, user_id)
        now = _now()
        next_reason_tags = (
            list(reason_tags)
            if reason_tags is not None
            else (current.reason_tags if current else [])
        )
        next_assigned_to = (
            assigned_to
            if assigned_to is not None
            else (current.assigned_to if current else "")
        )
        next_viewed_at = (
            viewed_at
            if viewed_at is not None
            else (current.viewed_at if current else "")
        )
        next_decision_at = (
            decision_at
            if decision_at is not None
            else (current.decision_at if current else "")
        )
        next_pushed_at = (
            pushed_at
            if pushed_at is not None
            else (current.pushed_at if current else "")
        )
        state = ReviewState(
            id=current.id if current else uuid4().hex,
            user_id=user_id,
            user_name=(
                user_name
                if user_name is not None
                else (current.user_name if current else "")
            ),
            resume_id=resume_id,
            read_status=read_status or (current.read_status if current else "unread"),
            decision=decision or (current.decision if current else "undecided"),
            reason_tags=next_reason_tags,
            note=note if note is not None else (current.note if current else ""),
            assigned_to=next_assigned_to,
            viewed_at=next_viewed_at,
            decision_at=next_decision_at,
            pushed_at=next_pushed_at,
            created_at=current.created_at if current else now,
            updated_at=now,
        )
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO resume_review_states (
                  id, user_id, user_name, resume_id, read_status, decision, reason_tags,
                  note, assigned_to, viewed_at, decision_at, pushed_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, resume_id) DO UPDATE SET
                  user_name = excluded.user_name,
                  read_status = excluded.read_status,
                  decision = excluded.decision,
                  reason_tags = excluded.reason_tags,
                  note = excluded.note,
                  assigned_to = excluded.assigned_to,
                  viewed_at = excluded.viewed_at,
                  decision_at = excluded.decision_at,
                  pushed_at = excluded.pushed_at,
                  updated_at = excluded.updated_at
                """,
                _state_params(state),
            )
            connection.commit()
        return state

    def append_event(
        self,
        *,
        resume_id: str,
        user_id: str,
        event_type: str,
        before: dict[str, object],
        after: dict[str, object],
    ) -> str:
        """追加审阅事件审计记录。"""

        event_id = uuid4().hex
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO resume_review_events (
                  id, resume_id, user_id, event_type, before_json, after_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    resume_id,
                    user_id,
                    event_type,
                    json.dumps(before, ensure_ascii=False, sort_keys=True),
                    json.dumps(after, ensure_ascii=False, sort_keys=True),
                    _now(),
                ),
            )
            connection.commit()
        return event_id

    def create_assignment(
        self,
        *,
        resume_id: str,
        from_user_id: str,
        assigned_to_user_id: str,
        source_decision_id: str,
        note: str,
    ) -> ReviewAssignment:
        """创建或复用待处理分配任务，避免同一简历重复入队。"""

        existing = self._active_assignment(resume_id, assigned_to_user_id)
        if existing:
            return existing
        now = _now()
        assignment = ReviewAssignment(
            id=uuid4().hex,
            resume_id=resume_id,
            from_user_id=from_user_id,
            assigned_to_user_id=assigned_to_user_id,
            status="pending",
            source_decision_id=source_decision_id,
            note=note,
            created_at=now,
            updated_at=now,
        )
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO resume_assignments (
                  id, resume_id, from_user_id, assigned_to_user_id, status,
                  source_decision_id, note, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assignment.id,
                    assignment.resume_id,
                    assignment.from_user_id,
                    assignment.assigned_to_user_id,
                    assignment.status,
                    assignment.source_decision_id,
                    assignment.note,
                    assignment.created_at,
                    assignment.updated_at,
                ),
            )
            connection.commit()
        return assignment

    def list_assignments(
        self,
        user_id: str,
        *,
        status: str = "pending",
    ) -> list[ReviewAssignment]:
        """List pending or completed assignments for one inbox."""

        if status not in {"pending", "completed"}:
            raise ValueError("invalid_assignment_status")

        with connect(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM resume_assignments
                WHERE assigned_to_user_id = ? AND status = ?
                ORDER BY updated_at DESC
                """,
                (user_id, status),
            ).fetchall()
        return [_assignment_from_row(row) for row in rows]

    def complete_shared_assignment(
        self,
        *,
        resume_id: str,
        shared_inbox_user_id: str,
        completed_by_user_id: str,
        completed_by_user_name: str,
        completion_action: str = "review_decision",
    ) -> ReviewAssignment | None:
        """Atomically complete the one shared pending task for a resume."""

        with connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM resume_assignments
                WHERE resume_id = ?
                  AND assigned_to_user_id = ?
                  AND status = 'pending'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (resume_id, shared_inbox_user_id),
            ).fetchone()
            if row is None:
                connection.commit()
                return None

            before = _assignment_from_row(row)
            now = _now()
            cursor = connection.execute(
                """
                UPDATE resume_assignments
                SET status = 'completed',
                    completion_action = ?,
                    completed_by_user_id = ?,
                    completed_by_user_name = ?,
                    completed_at = ?,
                    updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (
                    completion_action,
                    completed_by_user_id,
                    completed_by_user_name,
                    now,
                    now,
                    before.id,
                ),
            )
            if cursor.rowcount != 1:
                connection.commit()
                return None
            completed_row = connection.execute(
                "SELECT * FROM resume_assignments WHERE id = ?",
                (before.id,),
            ).fetchone()
            assert completed_row is not None
            completed = _assignment_from_row(completed_row)
            before_json = json.dumps(
                _assignment_audit_payload(before),
                ensure_ascii=False,
                sort_keys=True,
            )
            after_json = json.dumps(
                _assignment_audit_payload(completed),
                ensure_ascii=False,
                sort_keys=True,
            )
            connection.execute(
                """
                INSERT INTO resume_review_events (
                  id, resume_id, user_id, event_type, before_json, after_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    resume_id,
                    completed_by_user_id,
                    "assignment_completed",
                    before_json,
                    after_json,
                    now,
                ),
            )
            connection.commit()
        return completed

    def _active_assignment(
        self,
        resume_id: str,
        assigned_to_user_id: str,
    ) -> ReviewAssignment | None:
        with connect(self.database_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM resume_assignments
                WHERE resume_id = ? AND assigned_to_user_id = ? AND status = 'pending'
                """,
                (resume_id, assigned_to_user_id),
            ).fetchone()
        return _assignment_from_row(row) if row else None


def _state_params(state: ReviewState) -> tuple[object, ...]:
    return (
        state.id,
        state.user_id,
        state.user_name,
        state.resume_id,
        state.read_status,
        state.decision,
        json.dumps(state.reason_tags, ensure_ascii=False),
        state.note,
        state.assigned_to,
        state.viewed_at,
        state.decision_at,
        state.pushed_at,
        state.created_at,
        state.updated_at,
    )


def _state_from_row(row: sqlite3.Row) -> ReviewState:
    return ReviewState(
        id=row["id"],
        user_id=row["user_id"],
        user_name=row["user_name"],
        resume_id=row["resume_id"],
        read_status=row["read_status"],
        decision=row["decision"],
        reason_tags=_loads_list(row["reason_tags"]),
        note=row["note"],
        assigned_to=row["assigned_to"],
        viewed_at=row["viewed_at"],
        decision_at=row["decision_at"],
        pushed_at=row["pushed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _assignment_from_row(row: sqlite3.Row) -> ReviewAssignment:
    return ReviewAssignment(
        id=row["id"],
        resume_id=row["resume_id"],
        from_user_id=row["from_user_id"],
        assigned_to_user_id=row["assigned_to_user_id"],
        status=row["status"],
        completion_action=row["completion_action"],
        source_decision_id=row["source_decision_id"],
        note=row["note"],
        completed_by_user_id=row["completed_by_user_id"],
        completed_by_user_name=row["completed_by_user_name"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _assignment_audit_payload(assignment: ReviewAssignment) -> dict[str, object]:
    return {
        "id": assignment.id,
        "resumeId": assignment.resume_id,
        "fromUserId": assignment.from_user_id,
        "assignedToUserId": assignment.assigned_to_user_id,
        "status": assignment.status,
        "completionAction": assignment.completion_action,
        "completedByUserId": assignment.completed_by_user_id,
        "completedByUserName": assignment.completed_by_user_name,
        "completedAt": assignment.completed_at,
    }


def _loads_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _now() -> str:
    return datetime.now(UTC).isoformat()
