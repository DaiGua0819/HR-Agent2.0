"""Server-side idempotent merge service for automatic synchronization batches."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.db.engine import connect, run_migrations
from app.domain.auto_sync.models import SyncBatch, SyncFile, SyncMessage, SyncResume, SyncSession

_PATH_KEYS = {
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
}
_SYNC_OWNED_PAYLOAD_KEYS = {
    "sourcePlatform",
    "source_platform",
    "sourceOwner",
    "source_owner",
    "linked_session_id",
    "linked_platform",
    "linked_owner",
    "linked_platform_conversation_id",
    "source_artifact_id",
    "sourceArtifactId",
}
_ALLOWED_FILE_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class AutoSyncConflict(RuntimeError):
    """Raised when a batch reuses a stable identity with different content."""


class AutoSyncService:
    def __init__(
        self,
        database_path: str | Path,
        *,
        files_root: str | Path,
        max_file_bytes: int = 20 * 1024 * 1024,
    ) -> None:
        self.database_path = Path(database_path)
        self.files_root = Path(files_root)
        self.max_file_bytes = int(max_file_bytes)
        run_migrations(self.database_path)

    def apply_batch(self, batch: SyncBatch, *, body_hash: str) -> dict[str, object]:
        existing = self._existing_receipt(batch.batch_id, body_hash)
        if existing is not None:
            return {**existing, "idempotent": True}

        stored_files: dict[str, Path] = {}
        files_stored = 0
        files_reused = 0
        for resume in batch.resumes:
            if resume.file is None:
                continue
            stored_path, created = self._store_file(resume.file)
            stored_files[resume.id] = stored_path
            files_stored += int(created)
            files_reused += int(not created)

        result: dict[str, object] = {
            "batchId": batch.batch_id,
            "applied": True,
            "idempotent": False,
            "resumesInserted": 0,
            "resumesUpdated": 0,
            "resumesUnchanged": 0,
            "sessionsInserted": 0,
            "sessionsUpdated": 0,
            "sessionsUnchanged": 0,
            "messagesInserted": 0,
            "messagesDuplicate": 0,
            "operationEventsUpserted": 0,
            "runtimeStatusesUpserted": 0,
            "filesStored": files_stored,
            "filesReused": files_reused,
        }
        with connect(self.database_path) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                receipt = self._receipt_in_connection(connection, batch.batch_id)
                if receipt is not None:
                    if str(receipt["body_hash"]) != body_hash:
                        raise AutoSyncConflict("auto_sync_batch_id_conflict")
                    connection.rollback()
                    stored = json.loads(str(receipt["result"]))
                    return {**stored, "idempotent": True}

                session_mapping = self._merge_sessions(connection, batch, result)
                self._merge_messages(connection, batch, session_mapping, result)
                self._merge_resumes(
                    connection,
                    batch,
                    session_mapping,
                    stored_files,
                    result,
                )
                self._merge_operation_events(connection, batch, result)
                self._merge_runtime_statuses(connection, batch, result)
                connection.execute(
                    """
                    INSERT INTO sync_receipts (batch_id, body_hash, source, result, applied_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        batch.batch_id,
                        body_hash,
                        batch.source,
                        json.dumps(result, ensure_ascii=False, sort_keys=True),
                        _now_iso(),
                    ),
                )
                violations = list(connection.execute("PRAGMA foreign_key_check"))
                if violations:
                    raise RuntimeError("auto_sync_foreign_key_check_failed")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return result

    @staticmethod
    def _merge_operation_events(
        connection: sqlite3.Connection,
        batch: SyncBatch,
        result: dict[str, object],
    ) -> None:
        for item in batch.operation_events:
            connection.execute(
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
                ),
            )
            result["operationEventsUpserted"] = int(result["operationEventsUpserted"]) + 1

    @staticmethod
    def _merge_runtime_statuses(
        connection: sqlite3.Connection,
        batch: SyncBatch,
        result: dict[str, object],
    ) -> None:
        for item in batch.runtime_statuses:
            connection.execute(
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
                ),
            )
            result["runtimeStatusesUpserted"] = int(result["runtimeStatusesUpserted"]) + 1

    def _existing_receipt(
        self,
        batch_id: str,
        body_hash: str,
    ) -> dict[str, object] | None:
        with connect(self.database_path) as connection:
            row = self._receipt_in_connection(connection, batch_id)
        if row is None:
            return None
        if str(row["body_hash"]) != body_hash:
            raise AutoSyncConflict("auto_sync_batch_id_conflict")
        return json.loads(str(row["result"]))

    @staticmethod
    def _receipt_in_connection(
        connection: sqlite3.Connection,
        batch_id: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT body_hash, result FROM sync_receipts WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()

    def _merge_sessions(
        self,
        connection: sqlite3.Connection,
        batch: SyncBatch,
        result: dict[str, object],
    ) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for session in batch.sessions:
            target = connection.execute(
                "SELECT * FROM conversation_sessions WHERE id = ?",
                (session.id,),
            ).fetchone()
            if target is None and session.platform_conversation_id:
                target = connection.execute(
                    """
                    SELECT * FROM conversation_sessions
                    WHERE platform = ? AND owner = ?
                      AND platform_conversation_id = ? AND position = ?
                    """,
                    (
                        session.platform,
                        session.owner,
                        session.platform_conversation_id,
                        session.position,
                    ),
                ).fetchone()
            if target is None:
                connection.execute(
                    """
                    INSERT INTO conversation_sessions (
                      id, platform, owner, candidate_name, position, applied_position,
                      platform_conversation_id, label, current_stage, next_action,
                      recent_messages_fingerprint, identity_confidence, identity_warnings,
                      last_seen_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _session_values(session),
                )
                mapping[session.id] = session.id
                result["sessionsInserted"] = int(result["sessionsInserted"]) + 1
                continue
            target_id = str(target["id"])
            mapping[session.id] = target_id
            self._assert_session_identity(session, target)
            if session.updated_at <= str(target["updated_at"]):
                result["sessionsUnchanged"] = int(result["sessionsUnchanged"]) + 1
                continue
            connection.execute(
                """
                UPDATE conversation_sessions SET
                  candidate_name = ?, applied_position = ?, label = ?, current_stage = ?,
                  next_action = ?, recent_messages_fingerprint = ?, identity_confidence = ?,
                  identity_warnings = ?, last_seen_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    session.candidate_name,
                    session.applied_position,
                    session.label,
                    session.current_stage,
                    session.next_action,
                    session.recent_messages_fingerprint,
                    session.identity_confidence,
                    session.identity_warnings,
                    session.last_seen_at,
                    session.updated_at,
                    target_id,
                ),
            )
            result["sessionsUpdated"] = int(result["sessionsUpdated"]) + 1
        return mapping

    @staticmethod
    def _assert_session_identity(session: SyncSession, target: sqlite3.Row) -> None:
        for field_name, source_value in (
            ("platform", session.platform),
            ("owner", session.owner),
            ("platform_conversation_id", session.platform_conversation_id),
            ("position", session.position),
        ):
            target_value = str(target[field_name] or "")
            if source_value and target_value and source_value != target_value:
                raise AutoSyncConflict(
                    f"auto_sync_session_identity_conflict:{session.id}:{field_name}"
                )

    @staticmethod
    def _merge_messages(
        connection: sqlite3.Connection,
        batch: SyncBatch,
        session_mapping: dict[str, str],
        result: dict[str, object],
    ) -> None:
        for message in batch.messages:
            target_session_id = session_mapping.get(message.session_id, message.session_id)
            session_exists = connection.execute(
                "SELECT 1 FROM conversation_sessions WHERE id = ?",
                (target_session_id,),
            ).fetchone()
            if session_exists is None:
                raise AutoSyncConflict(
                    f"auto_sync_message_session_missing:{message.id}:{target_session_id}"
                )
            existing = connection.execute(
                "SELECT * FROM conversation_messages WHERE id = ?",
                (message.id,),
            ).fetchone()
            if existing is not None:
                if _stored_message_signature(existing) != _incoming_message_signature(
                    message,
                    target_session_id,
                ):
                    raise AutoSyncConflict(f"auto_sync_message_id_conflict:{message.id}")
                result["messagesDuplicate"] = int(result["messagesDuplicate"]) + 1
                continue
            duplicate_hash = connection.execute(
                """
                SELECT 1 FROM conversation_messages
                WHERE session_id = ? AND message_hash = ?
                """,
                (target_session_id, message.message_hash),
            ).fetchone()
            if duplicate_hash is not None:
                result["messagesDuplicate"] = int(result["messagesDuplicate"]) + 1
                continue
            connection.execute(
                """
                INSERT INTO conversation_messages (
                  id, session_id, sender, text, raw_text, sent_at,
                  platform_message_id, message_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    target_session_id,
                    message.sender,
                    message.text,
                    message.raw_text,
                    message.sent_at,
                    message.platform_message_id,
                    message.message_hash,
                    message.created_at,
                ),
            )
            result["messagesInserted"] = int(result["messagesInserted"]) + 1

    @staticmethod
    def _merge_resumes(
        connection: sqlite3.Connection,
        batch: SyncBatch,
        session_mapping: dict[str, str],
        stored_files: dict[str, Path],
        result: dict[str, object],
    ) -> None:
        for resume in batch.resumes:
            linked_session_id = session_mapping.get(
                resume.linked_session_id,
                resume.linked_session_id,
            )
            stored_path = stored_files.get(resume.id)
            incoming_payload = _server_payload(resume, stored_path)
            existing = connection.execute(
                "SELECT * FROM resumes WHERE id = ?",
                (resume.id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO resumes (
                      id, payload, phone_key, job_type, match_score, updated_at,
                      parsed_name, linked_session_id, linked_platform, linked_owner,
                      linked_platform_conversation_id, source_artifact_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resume.id,
                        json.dumps(incoming_payload, ensure_ascii=False, sort_keys=True),
                        resume.phone_key,
                        resume.job_type,
                        resume.match_score,
                        resume.updated_at,
                        resume.parsed_name,
                        linked_session_id,
                        resume.linked_platform,
                        resume.linked_owner,
                        resume.linked_platform_conversation_id,
                        resume.source_artifact_id,
                    ),
                )
                result["resumesInserted"] = int(result["resumesInserted"]) + 1
                continue
            existing_payload = json.loads(str(existing["payload"]))
            merged_payload = _merge_existing_payload(existing_payload, incoming_payload)
            updates = {
                "payload": json.dumps(merged_payload, ensure_ascii=False, sort_keys=True),
                "phone_key": existing["phone_key"] or resume.phone_key,
                "job_type": existing["job_type"] or resume.job_type,
                "match_score": (
                    existing["match_score"]
                    if existing["match_score"] is not None
                    else resume.match_score
                ),
                "updated_at": max(str(existing["updated_at"]), resume.updated_at),
                "parsed_name": existing["parsed_name"] or resume.parsed_name,
                "linked_session_id": linked_session_id or existing["linked_session_id"],
                "linked_platform": resume.linked_platform or existing["linked_platform"],
                "linked_owner": resume.linked_owner or existing["linked_owner"],
                "linked_platform_conversation_id": (
                    resume.linked_platform_conversation_id
                    or existing["linked_platform_conversation_id"]
                ),
                "source_artifact_id": resume.source_artifact_id or existing["source_artifact_id"],
            }
            changed = any(
                updates[key] != existing[key]
                for key in (
                    "payload",
                    "phone_key",
                    "job_type",
                    "match_score",
                    "updated_at",
                    "parsed_name",
                    "linked_session_id",
                    "linked_platform",
                    "linked_owner",
                    "linked_platform_conversation_id",
                    "source_artifact_id",
                )
            )
            if not changed:
                result["resumesUnchanged"] = int(result["resumesUnchanged"]) + 1
                continue
            connection.execute(
                """
                UPDATE resumes SET
                  payload = ?, phone_key = ?, job_type = ?, match_score = ?, updated_at = ?,
                  parsed_name = ?, linked_session_id = ?, linked_platform = ?, linked_owner = ?,
                  linked_platform_conversation_id = ?, source_artifact_id = ?
                WHERE id = ?
                """,
                (
                    updates["payload"],
                    updates["phone_key"],
                    updates["job_type"],
                    updates["match_score"],
                    updates["updated_at"],
                    updates["parsed_name"],
                    updates["linked_session_id"],
                    updates["linked_platform"],
                    updates["linked_owner"],
                    updates["linked_platform_conversation_id"],
                    updates["source_artifact_id"],
                    resume.id,
                ),
            )
            result["resumesUpdated"] = int(result["resumesUpdated"]) + 1

    def _store_file(self, file: SyncFile) -> tuple[Path, bool]:
        try:
            content = base64.b64decode(file.content_base64, validate=True)
        except ValueError as error:
            raise AutoSyncConflict("auto_sync_file_base64_invalid") from error
        if not content or len(content) > self.max_file_bytes:
            raise AutoSyncConflict("auto_sync_file_size_invalid")
        digest = hashlib.sha256(content).hexdigest()
        if digest != file.sha256.lower():
            raise AutoSyncConflict("auto_sync_file_hash_mismatch")
        suffix = Path(file.filename).suffix.lower()
        expected_media_type = _ALLOWED_FILE_TYPES.get(suffix)
        if expected_media_type is None or expected_media_type != file.media_type:
            raise AutoSyncConflict("auto_sync_file_type_invalid")
        destination = self.files_root / digest[:2] / f"{digest}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise AutoSyncConflict("auto_sync_stored_file_hash_mismatch")
            return destination, False
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        temporary.write_bytes(content)
        os.replace(temporary, destination)
        return destination, True


def _server_payload(resume: SyncResume, stored_path: Path | None) -> dict[str, object]:
    payload = {key: value for key, value in resume.payload.items() if key not in _PATH_KEYS}
    if stored_path is not None:
        payload["filePath"] = str(stored_path)
    return payload


def _merge_existing_payload(
    existing: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    merged = dict(existing)
    for key, value in incoming.items():
        if key in _PATH_KEYS or key in _SYNC_OWNED_PAYLOAD_KEYS:
            if value not in (None, ""):
                merged[key] = value
            continue
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = value
    return merged


def _session_values(session: SyncSession) -> tuple[object, ...]:
    return (
        session.id,
        session.platform,
        session.owner,
        session.candidate_name,
        session.position,
        session.applied_position,
        session.platform_conversation_id,
        session.label,
        session.current_stage,
        session.next_action,
        session.recent_messages_fingerprint,
        session.identity_confidence,
        session.identity_warnings,
        session.last_seen_at,
        session.created_at,
        session.updated_at,
    )


def _stored_message_signature(row: sqlite3.Row) -> tuple[str, ...]:
    return tuple(
        str(row[key] or "")
        for key in (
            "session_id",
            "sender",
            "text",
            "raw_text",
            "sent_at",
            "platform_message_id",
            "message_hash",
        )
    )


def _incoming_message_signature(message: SyncMessage, session_id: str) -> tuple[str, ...]:
    return (
        session_id,
        str(message.sender),
        str(message.text),
        str(message.raw_text),
        str(message.sent_at),
        str(message.platform_message_id),
        str(message.message_hash),
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
