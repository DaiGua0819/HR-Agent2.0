"""Durable one-at-a-time incremental synchronization worker."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.domain.auto_sync.auth import build_encrypted_sync_request

_PATH_KEYS = (
    "pdfPath",
    "pdf_path",
    "filePath",
    "file_path",
    "localPath",
    "local_path",
    "downloadPath",
    "download_path",
    "sourceFile",
    "source_file",
)
_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@dataclass(frozen=True)
class AutoSyncWorkerConfig:
    database_path: Path
    server_url: str
    secret: str
    state_path: Path
    pending_dir: Path
    source: str = "local-collector"
    interval_seconds: int = 60
    request_timeout_seconds: int = 90
    max_file_bytes: int = 18 * 1024 * 1024
    max_sessions_per_batch: int = 200
    max_messages_per_batch: int = 500


@dataclass(frozen=True)
class PendingSyncBatch:
    batch_id: str
    payload: dict[str, Any]
    cursors: dict[str, dict[str, str]]
    path: Path


class AutoSyncWorker:
    def __init__(self, config: AutoSyncWorkerConfig) -> None:
        self.config = config

    def bootstrap_current(self) -> dict[str, Any]:
        """Move cursors to the current database tail without sending old records."""

        with self._connect() as connection:
            state = self._load_state()
            state["resumeCursor"] = _max_cursor(connection, "resumes", "updated_at")
            state["sessionCursor"] = _max_cursor(
                connection,
                "conversation_sessions",
                "updated_at",
            )
            state["messageCursor"] = _max_cursor(
                connection,
                "conversation_messages",
                "created_at",
            )
            state["operationEventCursor"] = _max_cursor(
                connection,
                "automation_contact_events",
                "updated_at",
            )
            state["runtimeStatusCursor"] = _max_cursor(
                connection,
                "automation_runtime_status",
                "checked_at",
                id_column="target_key",
            )
            state["bootstrappedAt"] = _now_iso()
            self._write_state(state)
            return state

    def prepare_pending_batch(self) -> PendingSyncBatch | None:
        existing = self._load_pending()
        if existing is not None:
            return existing
        state = self._load_state()
        with self._connect() as connection:
            changed_resumes = _incremental_rows(
                connection,
                "resumes",
                "updated_at",
                state["resumeCursor"],
                limit=1,
            )
            changed_sessions = _incremental_rows(
                connection,
                "conversation_sessions",
                "updated_at",
                state["sessionCursor"],
                limit=self.config.max_sessions_per_batch,
            )
            changed_messages = _incremental_rows(
                connection,
                "conversation_messages",
                "created_at",
                state["messageCursor"],
                limit=self.config.max_messages_per_batch,
            )
            changed_operation_events = _incremental_rows(
                connection,
                "automation_contact_events",
                "updated_at",
                state["operationEventCursor"],
                limit=self.config.max_sessions_per_batch,
            )
            changed_runtime_statuses = _incremental_rows(
                connection,
                "automation_runtime_status",
                "checked_at",
                state["runtimeStatusCursor"],
                limit=50,
                id_column="target_key",
            )
            if not any(
                (
                    changed_resumes,
                    changed_sessions,
                    changed_messages,
                    changed_operation_events,
                    changed_runtime_statuses,
                )
            ):
                return None
            session_rows = {str(row["id"]): row for row in changed_sessions}
            dependency_ids = {
                str(row["session_id"])
                for row in changed_messages
                if row["session_id"]
            }
            dependency_ids.update(
                str(row["linked_session_id"])
                for row in changed_resumes
                if row["linked_session_id"]
            )
            missing_ids = sorted(dependency_ids - set(session_rows))
            if missing_ids:
                placeholders = ",".join("?" for _ in missing_ids)
                dependencies = connection.execute(
                    f"SELECT * FROM conversation_sessions WHERE id IN ({placeholders})",
                    missing_ids,
                )
                session_rows.update({str(row["id"]): row for row in dependencies})

            payload: dict[str, Any] = {
                "source": self.config.source,
                "createdAt": _now_iso(),
                "resumes": [self._resume_payload(row) for row in changed_resumes],
                "sessions": [_session_payload(row) for row in session_rows.values()],
                "messages": [_message_payload(row) for row in changed_messages],
                "operationEvents": [
                    _operation_event_payload(row) for row in changed_operation_events
                ],
                "runtimeStatuses": [
                    _runtime_status_payload(row) for row in changed_runtime_statuses
                ],
            }
            canonical = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            batch_id = "batch-" + hashlib.sha256(canonical).hexdigest()
            payload["batchId"] = batch_id
            cursors = {
                "resumeCursor": _cursor_after(changed_resumes, "updated_at", state["resumeCursor"]),
                "sessionCursor": _cursor_after(
                    changed_sessions,
                    "updated_at",
                    state["sessionCursor"],
                ),
                "messageCursor": _cursor_after(
                    changed_messages,
                    "created_at",
                    state["messageCursor"],
                ),
                "operationEventCursor": _cursor_after(
                    changed_operation_events,
                    "updated_at",
                    state["operationEventCursor"],
                ),
                "runtimeStatusCursor": _cursor_after(
                    changed_runtime_statuses,
                    "checked_at",
                    state["runtimeStatusCursor"],
                    id_column="target_key",
                ),
            }
        self.config.pending_dir.mkdir(parents=True, exist_ok=True)
        path = self.config.pending_dir / f"{batch_id}.json"
        _write_json_atomic(path, {"payload": payload, "cursors": cursors})
        return PendingSyncBatch(batch_id, payload, cursors, path)

    def send_pending(self, pending: PendingSyncBatch) -> dict[str, Any]:
        plaintext = json.dumps(
            pending.payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        transmitted_body, headers = build_encrypted_sync_request(
            plaintext,
            self.config.secret,
        )
        endpoint = self.config.server_url.rstrip("/") + "/api/internal/sync/batch"
        with httpx.Client(timeout=self.config.request_timeout_seconds) as client:
            response = client.post(endpoint, content=transmitted_body, headers=headers)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("applied") and not payload.get("idempotent"):
            raise RuntimeError("auto_sync_server_did_not_acknowledge")
        return payload

    def acknowledge(self, pending: PendingSyncBatch) -> None:
        state = self._load_state()
        state.update(pending.cursors)
        state["lastSuccessAt"] = _now_iso()
        state["lastBatchId"] = pending.batch_id
        state["lastError"] = ""
        state["consecutiveFailures"] = 0
        self._write_state(state)
        pending.path.unlink(missing_ok=True)

    def record_failure(self, error: Exception) -> None:
        state = self._load_state()
        state["lastError"] = f"{type(error).__name__}: {error}"[:500]
        state["lastFailureAt"] = _now_iso()
        state["consecutiveFailures"] = int(state.get("consecutiveFailures", 0)) + 1
        self._write_state(state)

    def run_once(self) -> dict[str, Any] | None:
        try:
            pending = self.prepare_pending_batch()
            if pending is None:
                return None
            result = self.send_pending(pending)
        except Exception as error:
            self.record_failure(error)
            raise
        self.acknowledge(pending)
        return result

    def run_forever(self) -> None:
        while True:
            try:
                result = self.run_once()
                if result is not None:
                    continue
                delay = max(5, self.config.interval_seconds)
            except Exception:
                failures = int(self._load_state().get("consecutiveFailures", 1))
                delay = min(600, max(60, 60 * (2 ** min(failures - 1, 4))))
            time.sleep(delay)

    def _resume_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(str(row["payload"]))
        item: dict[str, Any] = {
            "id": str(row["id"]),
            "payload": payload,
            "phoneKey": row["phone_key"],
            "jobType": row["job_type"],
            "matchScore": row["match_score"],
            "updatedAt": str(row["updated_at"]),
            "parsedName": str(row["parsed_name"] or ""),
            "linkedSessionId": str(row["linked_session_id"] or ""),
            "linkedPlatform": str(row["linked_platform"] or ""),
            "linkedOwner": str(row["linked_owner"] or ""),
            "linkedPlatformConversationId": str(
                row["linked_platform_conversation_id"] or ""
            ),
            "sourceArtifactId": str(row["source_artifact_id"] or ""),
        }
        file_payload = self._resume_file_payload(payload)
        if file_payload is not None:
            item["file"] = file_payload
        return item

    def _resume_file_payload(self, payload: dict[str, Any]) -> dict[str, str] | None:
        for key in _PATH_KEYS:
            value = payload.get(key)
            if not value:
                continue
            path = Path(str(value))
            media_type = _MEDIA_TYPES.get(path.suffix.lower())
            if not path.is_file() or media_type is None:
                continue
            size = path.stat().st_size
            if size < 1 or size > self.config.max_file_bytes:
                raise RuntimeError(f"auto_sync_resume_file_size_invalid:{path.name}:{size}")
            content = path.read_bytes()
            return {
                "sha256": hashlib.sha256(content).hexdigest(),
                "filename": path.name,
                "mediaType": media_type,
                "contentBase64": base64.b64encode(content).decode("ascii"),
            }
        return None

    def _load_pending(self) -> PendingSyncBatch | None:
        if not self.config.pending_dir.exists():
            return None
        paths = sorted(self.config.pending_dir.glob("batch-*.json"))
        if not paths:
            return None
        path = paths[0]
        stored = json.loads(path.read_text(encoding="utf-8"))
        payload = stored["payload"]
        return PendingSyncBatch(
            batch_id=str(payload["batchId"]),
            payload=payload,
            cursors=stored["cursors"],
            path=path,
        )

    def _load_state(self) -> dict[str, Any]:
        if self.config.state_path.is_file():
            state = json.loads(self.config.state_path.read_text(encoding="utf-8"))
            changed = False
            defaults = {
                "resumeCursor": _empty_cursor(),
                "sessionCursor": _empty_cursor(),
                "messageCursor": _empty_cursor(),
                "operationEventCursor": _empty_cursor(),
                "runtimeStatusCursor": _empty_cursor(),
                "lastSuccessAt": "",
                "lastError": "",
                "consecutiveFailures": 0,
            }
            for key, value in defaults.items():
                if key not in state:
                    state[key] = value
                    changed = True
            if changed:
                self._write_state(state)
            return state
        return {
            "resumeCursor": _empty_cursor(),
            "sessionCursor": _empty_cursor(),
            "messageCursor": _empty_cursor(),
            "operationEventCursor": _empty_cursor(),
            "runtimeStatusCursor": _empty_cursor(),
            "lastSuccessAt": "",
            "lastError": "",
            "consecutiveFailures": 0,
        }

    def _write_state(self, state: dict[str, Any]) -> None:
        _write_json_atomic(self.config.state_path, state)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.config.database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _incremental_rows(
    connection: sqlite3.Connection,
    table: str,
    timestamp_column: str,
    cursor: dict[str, str],
    *,
    limit: int,
    id_column: str = "id",
) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            f"""
            SELECT * FROM {table}
            WHERE {timestamp_column} > ?
               OR ({timestamp_column} = ? AND {id_column} > ?)
            ORDER BY {timestamp_column}, {id_column}
            LIMIT ?
            """,
            (cursor["timestamp"], cursor["timestamp"], cursor["id"], limit),
        )
    )


def _max_cursor(
    connection: sqlite3.Connection,
    table: str,
    timestamp_column: str,
    *,
    id_column: str = "id",
) -> dict[str, str]:
    row = connection.execute(
        f"SELECT {timestamp_column}, {id_column} FROM {table} "
        f"ORDER BY {timestamp_column} DESC, {id_column} DESC LIMIT 1"
    ).fetchone()
    return (
        {"timestamp": str(row[0]), "id": str(row[1])}
        if row is not None
        else _empty_cursor()
    )


def _cursor_after(
    rows: list[sqlite3.Row],
    timestamp_column: str,
    fallback: dict[str, str],
    *,
    id_column: str = "id",
) -> dict[str, str]:
    if not rows:
        return dict(fallback)
    row = rows[-1]
    return {"timestamp": str(row[timestamp_column]), "id": str(row[id_column])}


def _session_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "platform": str(row["platform"]),
        "owner": str(row["owner"]),
        "candidateName": str(row["candidate_name"]),
        "position": str(row["position"]),
        "appliedPosition": str(row["applied_position"]),
        "platformConversationId": str(row["platform_conversation_id"]),
        "label": str(row["label"]),
        "currentStage": str(row["current_stage"]),
        "nextAction": str(row["next_action"]),
        "recentMessagesFingerprint": str(row["recent_messages_fingerprint"]),
        "identityConfidence": str(row["identity_confidence"]),
        "identityWarnings": str(row["identity_warnings"]),
        "lastSeenAt": str(row["last_seen_at"]),
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }


def _message_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "sessionId": str(row["session_id"]),
        "sender": str(row["sender"]),
        "text": str(row["text"]),
        "rawText": str(row["raw_text"]),
        "sentAt": str(row["sent_at"]),
        "platformMessageId": str(row["platform_message_id"]),
        "messageHash": str(row["message_hash"]),
        "createdAt": str(row["created_at"]),
    }


def _operation_event_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "contactKey": str(row["contact_key"]),
        "owner": str(row["owner"]),
        "platform": str(row["platform"]),
        "candidateName": str(row["candidate_name"]),
        "jobType": str(row["job_type"]),
        "occurredAt": str(row["occurred_at"]),
        "action": str(row["action"]),
        "stage": str(row["stage"]),
        "processed": bool(row["processed"]),
        "sentCompanyInfo": bool(row["sent_company_info"]),
        "requestedResume": bool(row["requested_resume"]),
        "candidateQuestion": bool(row["candidate_question"]),
        "knowledgeAnswered": bool(row["knowledge_answered"]),
        "resumeAcquired": bool(row["resume_acquired"]),
        "resumeHandling": str(row["resume_handling"]),
        "resumeFileHash": str(row["resume_file_hash"]),
        "anomaly": bool(row["anomaly"]),
        "anomalyReason": str(row["anomaly_reason"]),
        "payload": json.loads(str(row["payload"] or "{}")),
        "updatedAt": str(row["updated_at"]),
    }


def _runtime_status_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "targetKey": str(row["target_key"]),
        "owner": str(row["owner"]),
        "platform": str(row["platform"]),
        "status": str(row["status"]),
        "agentReady": bool(row["agent_ready"]),
        "browserReady": bool(row["browser_ready"]),
        "cdpReady": bool(row["cdp_ready"]),
        "agentBusy": bool(row["agent_busy"]),
        "authenticated": bool(row["authenticated"]),
        "needsLogin": bool(row["needs_login"]),
        "securityVerification": bool(row["security_verification"]),
        "accountAbnormal": bool(row["account_abnormal"]),
        "pagePresent": bool(row["page_present"]),
        "paused": bool(row["paused"]),
        "reason": str(row["reason"]),
        "checkedAt": str(row["checked_at"]),
        "receivedAt": str(row["received_at"]),
    }


def _empty_cursor() -> dict[str, str]:
    return {"timestamp": "", "id": ""}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
