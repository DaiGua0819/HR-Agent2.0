"""SQLite persistence for automation monitoring."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from app.db.engine import connect, run_migrations
from app.domain.automation_monitoring.models import (
    AutomationContactEvent,
    AutomationRuntimeStatus,
)


class AutomationMonitoringRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        run_migrations(self.database_path)

    def upsert_events(self, events: Iterable[AutomationContactEvent | dict[str, object]]) -> int:
        normalized = [
            item
            if isinstance(item, AutomationContactEvent)
            else AutomationContactEvent.model_validate(item)
            for item in events
        ]
        with connect(self.database_path) as connection:
            connection.executemany(
                """
                INSERT INTO automation_contact_events (
                  id, contact_key, owner, platform, candidate_name, job_type,
                  occurred_at, action, stage, processed, sent_company_info,
                  requested_resume, candidate_question, knowledge_answered,
                  resume_acquired, resume_handling, resume_file_hash, anomaly,
                  anomaly_reason, payload, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  contact_key=excluded.contact_key, owner=excluded.owner,
                  platform=excluded.platform, candidate_name=excluded.candidate_name,
                  job_type=excluded.job_type, occurred_at=excluded.occurred_at,
                  action=excluded.action, stage=excluded.stage,
                  processed=excluded.processed,
                  sent_company_info=excluded.sent_company_info,
                  requested_resume=excluded.requested_resume,
                  candidate_question=excluded.candidate_question,
                  knowledge_answered=excluded.knowledge_answered,
                  resume_acquired=excluded.resume_acquired,
                  resume_handling=excluded.resume_handling,
                  resume_file_hash=excluded.resume_file_hash,
                  anomaly=excluded.anomaly, anomaly_reason=excluded.anomaly_reason,
                  payload=excluded.payload, updated_at=excluded.updated_at
                """,
                [
                    (
                        item.id,
                        item.contact_key,
                        item.owner,
                        item.platform,
                        item.candidate_name,
                        item.job_type,
                        item.occurred_at,
                        item.action,
                        item.stage,
                        int(item.processed),
                        int(item.sent_company_info),
                        int(item.requested_resume),
                        int(item.candidate_question),
                        int(item.knowledge_answered),
                        int(item.resume_acquired),
                        item.resume_handling,
                        item.resume_file_hash,
                        int(item.anomaly),
                        item.anomaly_reason,
                        json.dumps(item.payload, ensure_ascii=False, sort_keys=True),
                        item.updated_at,
                    )
                    for item in normalized
                ],
            )
            connection.commit()
        return len(normalized)

    def list_events(
        self,
        *,
        start: str,
        end: str,
        platform: str = "",
        owner: str = "",
        job_type: str = "",
    ) -> list[dict[str, object]]:
        clauses = ["occurred_at >= ?", "occurred_at < ?"]
        params: list[object] = [start, end]
        for column, value in (("platform", platform), ("owner", owner), ("job_type", job_type)):
            if value and value != "all":
                clauses.append(f"{column} = ?")
                params.append(value)
        with connect(self.database_path, read_only=True) as connection:
            rows = connection.execute(
                f"SELECT * FROM automation_contact_events WHERE {' AND '.join(clauses)} "
                "ORDER BY occurred_at DESC, id DESC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve_resume_ids(
        self,
        events: list[dict[str, object]],
    ) -> dict[str, str]:
        session_by_event: dict[str, str] = {}
        conversation_by_event: dict[str, tuple[str, str, str]] = {}
        for event in events:
            event_id = str(event.get("id") or "")
            payload = _json_object(event.get("payload"))
            contact_key = str(event.get("contact_key") or "")
            session_id = str(payload.get("sessionId") or _session_id(contact_key))
            conversation_id = str(
                payload.get("conversationId") or _conversation_id(contact_key)
            )
            if event_id and session_id:
                session_by_event[event_id] = session_id
            elif event_id and conversation_id:
                conversation_by_event[event_id] = (
                    str(event.get("platform") or ""),
                    str(event.get("owner") or ""),
                    conversation_id,
                )

        session_resume_ids: dict[str, str] = {}
        conversation_resume_ids: dict[tuple[str, str, str], str] = {}
        with connect(self.database_path, read_only=True) as connection:
            session_ids = sorted(set(session_by_event.values()))
            if session_ids:
                placeholders = ",".join("?" for _ in session_ids)
                rows = connection.execute(
                    "SELECT id, linked_session_id FROM resumes "
                    f"WHERE linked_session_id IN ({placeholders}) "
                    "ORDER BY updated_at DESC, id DESC",
                    session_ids,
                ).fetchall()
                for row in rows:
                    session_resume_ids.setdefault(str(row["linked_session_id"]), str(row["id"]))

            conversation_ids = sorted(
                {identity[2] for identity in conversation_by_event.values()}
            )
            if conversation_ids:
                placeholders = ",".join("?" for _ in conversation_ids)
                rows = connection.execute(
                    "SELECT id, linked_platform, linked_owner, "
                    "linked_platform_conversation_id FROM resumes "
                    f"WHERE linked_platform_conversation_id IN ({placeholders}) "
                    "ORDER BY updated_at DESC, id DESC",
                    conversation_ids,
                ).fetchall()
                for row in rows:
                    identity = (
                        str(row["linked_platform"]),
                        str(row["linked_owner"]),
                        str(row["linked_platform_conversation_id"]),
                    )
                    conversation_resume_ids.setdefault(identity, str(row["id"]))

        result = {
            event_id: session_resume_ids[session_id]
            for event_id, session_id in session_by_event.items()
            if session_id in session_resume_ids
        }
        result.update(
            {
                event_id: conversation_resume_ids[identity]
                for event_id, identity in conversation_by_event.items()
                if identity in conversation_resume_ids
            }
        )
        return result

    def upsert_runtime_statuses(
        self,
        statuses: Iterable[AutomationRuntimeStatus | dict[str, object]],
    ) -> int:
        normalized = [
            item
            if isinstance(item, AutomationRuntimeStatus)
            else AutomationRuntimeStatus.model_validate(item)
            for item in statuses
        ]
        with connect(self.database_path) as connection:
            connection.executemany(
                """
                INSERT INTO automation_runtime_status (
                  target_key, owner, platform, status, agent_ready, browser_ready,
                  cdp_ready, agent_busy, authenticated, needs_login,
                  security_verification, account_abnormal, page_present, paused,
                  reason, checked_at, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(target_key) DO UPDATE SET
                  owner=excluded.owner, platform=excluded.platform, status=excluded.status,
                  agent_ready=excluded.agent_ready, browser_ready=excluded.browser_ready,
                  cdp_ready=excluded.cdp_ready, agent_busy=excluded.agent_busy,
                  authenticated=excluded.authenticated, needs_login=excluded.needs_login,
                  security_verification=excluded.security_verification,
                  account_abnormal=excluded.account_abnormal,
                  page_present=excluded.page_present, paused=excluded.paused,
                  reason=excluded.reason, checked_at=excluded.checked_at,
                  received_at=excluded.received_at
                """,
                [
                    (
                        item.target_key,
                        item.owner,
                        item.platform,
                        item.status,
                        int(item.agent_ready),
                        int(item.browser_ready),
                        int(item.cdp_ready),
                        int(item.agent_busy),
                        int(item.authenticated),
                        int(item.needs_login),
                        int(item.security_verification),
                        int(item.account_abnormal),
                        int(item.page_present),
                        int(item.paused),
                        item.reason,
                        item.checked_at,
                        item.received_at,
                    )
                    for item in normalized
                ],
            )
            connection.commit()
        return len(normalized)

    def list_runtime_statuses(self) -> list[dict[str, object]]:
        with connect(self.database_path, read_only=True) as connection:
            rows = connection.execute(
                "SELECT * FROM automation_runtime_status ORDER BY owner, platform"
            ).fetchall()
        return [dict(row) for row in rows]


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _session_id(contact_key: str) -> str:
    parts = contact_key.split("|", 3)
    return parts[1] if len(parts) >= 2 and parts[0] == "session" else ""


def _conversation_id(contact_key: str) -> str:
    parts = contact_key.split("|", 3)
    return parts[3] if len(parts) == 4 and parts[0] == "conversation" else ""
