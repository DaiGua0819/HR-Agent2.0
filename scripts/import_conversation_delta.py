"""Dry-run or apply an idempotent conversation-history delta to a resume database."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from scripts.export_conversation_delta import (
        FORMAT_VERSION,
        MESSAGE_COLUMNS,
        SESSION_COLUMNS,
    )
except ModuleNotFoundError:  # Direct execution places the scripts directory on sys.path.
    from export_conversation_delta import (  # type: ignore[no-redef]
        FORMAT_VERSION,
        MESSAGE_COLUMNS,
        SESSION_COLUMNS,
    )

_IDENTITY_FIELDS = ("platform", "owner", "platform_conversation_id", "position")
_MUTABLE_SESSION_FIELDS = (
    "candidate_name",
    "applied_position",
    "label",
    "current_stage",
    "next_action",
    "recent_messages_fingerprint",
    "identity_confidence",
    "identity_warnings",
    "last_seen_at",
    "updated_at",
)


@dataclass(frozen=True)
class ConversationSyncConfig:
    target_db: Path
    delta_db: Path
    manifest_path: Path | None = None
    report_path: Path | None = None
    backup_dir: Path | None = None
    apply: bool = False
    yes: bool = False


@dataclass
class _SyncPlan:
    session_mapping: dict[str, str] = field(default_factory=dict)
    session_inserts: list[dict[str, Any]] = field(default_factory=list)
    session_updates: list[dict[str, Any]] = field(default_factory=list)
    message_inserts: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=dict)


def run_sync(config: ConversationSyncConfig) -> dict[str, Any]:
    target = Path(config.target_db)
    delta = Path(config.delta_db)
    _validate_config(config, target=target, delta=delta)
    manifest = _verify_delta(delta, config.manifest_path)
    delta_sessions = _load_rows(delta, "conversation_sessions", SESSION_COLUMNS)
    delta_messages = _load_rows(delta, "conversation_messages", MESSAGE_COLUMNS)

    with closing(sqlite3.connect(target, timeout=30)) as target_connection:
        target_connection.row_factory = sqlite3.Row
        _assert_target_schema(target_connection)
        target_quick_check = str(target_connection.execute("PRAGMA quick_check").fetchone()[0])
        if target_quick_check != "ok":
            raise RuntimeError(f"conversation_target_quick_check_failed: {target_quick_check}")
        target_sessions = _rows_from_connection(
            target_connection,
            "conversation_sessions",
            SESSION_COLUMNS,
        )
        target_messages = _rows_from_connection(
            target_connection,
            "conversation_messages",
            MESSAGE_COLUMNS,
        )
        linked_before = _linked_resume_count(target_connection)
        linked_session_ids = _linked_resume_session_ids(target_connection)

    plan = _build_plan(
        delta_sessions=delta_sessions,
        delta_messages=delta_messages,
        target_sessions=target_sessions,
        target_messages=target_messages,
    )
    final_session_ids = {str(row["id"]) for row in target_sessions}
    final_session_ids.update(str(row["id"]) for row in plan.session_inserts)
    report = _build_report(
        config=config,
        manifest=manifest,
        plan=plan,
        source_session_count=len(delta_sessions),
        source_message_count=len(delta_messages),
        target_session_count=len(target_sessions),
        target_message_count=len(target_messages),
        target_quick_check=target_quick_check,
        linked_before=linked_before,
        linked_projected=sum(
            1 for session_id in linked_session_ids if session_id in final_session_ids
        ),
    )
    if not config.apply:
        _write_report(config.report_path, report)
        return report
    if not config.yes:
        raise RuntimeError("conversation_sync_apply_requires_yes")
    if plan.conflicts:
        _write_report(config.report_path, report)
        raise RuntimeError(
            f"conversation_sync_blocking_conflicts: {len(plan.conflicts)}"
        )

    backup_dir = Path(config.backup_dir) if config.backup_dir else target.parent / "backups"
    backup_path = _backup_target(target, backup_dir)
    report["backupPath"] = str(backup_path)
    _apply_plan(target, plan, report)
    report["applied"] = True
    report["dryRun"] = False
    report["targetQuickCheckAfter"] = _quick_check(target)
    report["foreignKeyViolationsAfter"] = _foreign_key_violation_count(target)
    with closing(sqlite3.connect(target)) as connection:
        report["targetSessionsAfter"] = _table_count(connection, "conversation_sessions")
        report["targetMessagesAfter"] = _table_count(connection, "conversation_messages")
        report["linkedResumesAfter"] = _linked_resume_count(connection)
    if report["targetQuickCheckAfter"] != "ok" or report["foreignKeyViolationsAfter"]:
        raise RuntimeError("conversation_sync_post_apply_validation_failed")
    _write_report(config.report_path, report)
    return report


def _validate_config(
    config: ConversationSyncConfig,
    *,
    target: Path,
    delta: Path,
) -> None:
    if not target.is_file():
        raise FileNotFoundError(f"conversation_target_not_found: {target}")
    if not delta.is_file():
        raise FileNotFoundError(f"conversation_delta_not_found: {delta}")
    if target.resolve() == delta.resolve():
        raise ValueError("conversation_delta_must_not_be_target")
    if config.apply and config.backup_dir is not None:
        Path(config.backup_dir).mkdir(parents=True, exist_ok=True)


def _verify_delta(delta: Path, manifest_path: Path | None) -> dict[str, Any]:
    quick_check = _quick_check(delta)
    if quick_check != "ok":
        raise RuntimeError(f"conversation_delta_quick_check_failed: {quick_check}")
    if _foreign_key_violation_count(delta):
        raise RuntimeError("conversation_delta_foreign_key_check_failed")
    with closing(sqlite3.connect(delta)) as connection:
        _assert_delta_schema(connection)
        metadata = dict(
            connection.execute("SELECT key, value FROM conversation_sync_metadata")
        )
    if metadata.get("formatVersion") != FORMAT_VERSION:
        raise RuntimeError(
            "conversation_delta_format_mismatch: "
            f"{metadata.get('formatVersion')!r}"
        )
    resolved_manifest = (
        Path(manifest_path)
        if manifest_path
        else delta.with_suffix(".manifest.json")
    )
    payload: dict[str, Any] = {
        "formatVersion": metadata["formatVersion"],
        "sessionCount": int(metadata.get("sessionCount", 0)),
        "messageCount": int(metadata.get("messageCount", 0)),
        "quickCheck": quick_check,
        "sha256": _sha256(delta),
        "manifestPath": "",
    }
    if resolved_manifest.is_file():
        loaded = json.loads(resolved_manifest.read_text(encoding="utf-8"))
        expected_hash = str(loaded.get("sha256") or "")
        if expected_hash and expected_hash != payload["sha256"]:
            raise RuntimeError("conversation_delta_sha256_mismatch")
        if str(loaded.get("formatVersion") or "") != FORMAT_VERSION:
            raise RuntimeError("conversation_delta_manifest_format_mismatch")
        payload.update(loaded)
        payload["manifestPath"] = str(resolved_manifest)
    return payload


def _build_plan(
    *,
    delta_sessions: list[dict[str, Any]],
    delta_messages: list[dict[str, Any]],
    target_sessions: list[dict[str, Any]],
    target_messages: list[dict[str, Any]],
) -> _SyncPlan:
    plan = _SyncPlan(
        metrics={
            "sameIdSessions": 0,
            "naturalIdentityMappings": 0,
            "sessionsToKeep": 0,
            "messagesDuplicateById": 0,
            "messagesDuplicateByHash": 0,
            "messagesBlockedBySession": 0,
        }
    )
    target_by_id = {str(row["id"]): row for row in target_sessions}
    target_by_identity = {
        key: row
        for row in target_sessions
        if (key := _natural_identity(row)) is not None
    }

    for source in delta_sessions:
        source_id = str(source["id"])
        target = target_by_id.get(source_id)
        if target is not None:
            plan.metrics["sameIdSessions"] += 1
            mismatch = _identity_mismatches(source, target)
            if mismatch:
                plan.conflicts.append(
                    {
                        "type": "session_identity_conflict",
                        "sourceSessionId": source_id,
                        "targetSessionId": source_id,
                        "fields": mismatch,
                    }
                )
                continue
        else:
            identity = _natural_identity(source)
            target = target_by_identity.get(identity) if identity is not None else None
            if target is not None:
                plan.metrics["naturalIdentityMappings"] += 1
            else:
                inserted = dict(source)
                plan.session_mapping[source_id] = source_id
                plan.session_inserts.append(inserted)
                target_by_id[source_id] = inserted
                if identity is not None:
                    target_by_identity[identity] = inserted
                continue

        target_id = str(target["id"])
        plan.session_mapping[source_id] = target_id
        if _is_newer(str(source["updated_at"]), str(target["updated_at"])):
            plan.session_updates.append(_merged_session(source, target))
        else:
            plan.metrics["sessionsToKeep"] += 1

    target_messages_by_id = {str(row["id"]): row for row in target_messages}
    target_messages_by_hash = {
        (str(row["session_id"]), str(row["message_hash"])): row
        for row in target_messages
    }
    for source in delta_messages:
        source_session_id = str(source["session_id"])
        target_session_id = plan.session_mapping.get(source_session_id)
        if target_session_id is None:
            plan.metrics["messagesBlockedBySession"] += 1
            continue
        mapped = {**source, "session_id": target_session_id}
        message_id = str(mapped["id"])
        existing_by_id = target_messages_by_id.get(message_id)
        if existing_by_id is not None:
            if _message_signature(mapped) == _message_signature(existing_by_id):
                plan.metrics["messagesDuplicateById"] += 1
            else:
                plan.conflicts.append(
                    {
                        "type": "message_content_conflict",
                        "messageId": message_id,
                        "sourceSessionId": source_session_id,
                        "targetSessionId": target_session_id,
                    }
                )
            continue
        hash_key = (target_session_id, str(mapped["message_hash"]))
        existing_by_hash = target_messages_by_hash.get(hash_key)
        if existing_by_hash is not None:
            if _message_content_signature(mapped) == _message_content_signature(
                existing_by_hash
            ):
                plan.metrics["messagesDuplicateByHash"] += 1
            else:
                plan.conflicts.append(
                    {
                        "type": "message_hash_conflict",
                        "messageId": message_id,
                        "targetMessageId": str(existing_by_hash["id"]),
                        "targetSessionId": target_session_id,
                    }
                )
            continue
        plan.message_inserts.append(mapped)
        target_messages_by_id[message_id] = mapped
        target_messages_by_hash[hash_key] = mapped
    return plan


def _build_report(
    *,
    config: ConversationSyncConfig,
    manifest: dict[str, Any],
    plan: _SyncPlan,
    source_session_count: int,
    source_message_count: int,
    target_session_count: int,
    target_message_count: int,
    target_quick_check: str,
    linked_before: int,
    linked_projected: int,
) -> dict[str, Any]:
    return {
        "dryRun": not config.apply,
        "applied": False,
        "targetDb": str(config.target_db),
        "deltaDb": str(config.delta_db),
        "deltaFormatVersion": manifest.get("formatVersion"),
        "deltaSha256": manifest.get("sha256"),
        "deltaManifestPath": manifest.get("manifestPath", ""),
        "deltaQuickCheck": manifest.get("quickCheck", ""),
        "targetQuickCheckBefore": target_quick_check,
        "targetQuickCheckAfter": "",
        "foreignKeyViolationsAfter": 0,
        "sourceSessions": source_session_count,
        "sourceMessages": source_message_count,
        "targetSessionsBefore": target_session_count,
        "targetMessagesBefore": target_message_count,
        "sameIdSessions": plan.metrics["sameIdSessions"],
        "naturalIdentityMappings": plan.metrics["naturalIdentityMappings"],
        "sessionsToInsert": len(plan.session_inserts),
        "sessionsToUpdate": len(plan.session_updates),
        "sessionsToKeep": plan.metrics["sessionsToKeep"],
        "messagesDuplicateById": plan.metrics["messagesDuplicateById"],
        "messagesDuplicateByHash": plan.metrics["messagesDuplicateByHash"],
        "messagesBlockedBySession": plan.metrics["messagesBlockedBySession"],
        "messagesToInsert": len(plan.message_inserts),
        "blockingConflictCount": len(plan.conflicts),
        "blockingConflicts": plan.conflicts,
        "projectedSessions": target_session_count + len(plan.session_inserts),
        "projectedMessages": target_message_count + len(plan.message_inserts),
        "linkedResumesBefore": linked_before,
        "linkedResumesProjected": linked_projected,
        "linkedResumesAfter": 0,
        "targetSessionsAfter": 0,
        "targetMessagesAfter": 0,
        "backupPath": "",
    }


def _apply_plan(target: Path, plan: _SyncPlan, report: dict[str, Any]) -> None:
    session_insert_sql = _insert_sql("conversation_sessions", SESSION_COLUMNS)
    message_insert_sql = _insert_sql("conversation_messages", MESSAGE_COLUMNS)
    session_update_sql = """
        UPDATE conversation_sessions SET
          candidate_name = ?, applied_position = ?, label = ?, current_stage = ?,
          next_action = ?, recent_messages_fingerprint = ?, identity_confidence = ?,
          identity_warnings = ?, last_seen_at = ?, created_at = ?, updated_at = ?
        WHERE id = ?
    """
    with closing(sqlite3.connect(target, timeout=30)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                session_insert_sql,
                [_row_values(row, SESSION_COLUMNS) for row in plan.session_inserts],
            )
            connection.executemany(
                session_update_sql,
                [
                    (
                        row["candidate_name"],
                        row["applied_position"],
                        row["label"],
                        row["current_stage"],
                        row["next_action"],
                        row["recent_messages_fingerprint"],
                        row["identity_confidence"],
                        row["identity_warnings"],
                        row["last_seen_at"],
                        row["created_at"],
                        row["updated_at"],
                        row["id"],
                    )
                    for row in plan.session_updates
                ],
            )
            connection.executemany(
                message_insert_sql,
                [_row_values(row, MESSAGE_COLUMNS) for row in plan.message_inserts],
            )
            actual_sessions = _table_count(connection, "conversation_sessions")
            actual_messages = _table_count(connection, "conversation_messages")
            if actual_sessions != report["projectedSessions"]:
                raise RuntimeError("conversation_sync_session_count_mismatch")
            if actual_messages != report["projectedMessages"]:
                raise RuntimeError("conversation_sync_message_count_mismatch")
            violations = list(connection.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError("conversation_sync_foreign_key_check_failed")
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _merged_session(source: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    merged = dict(target)
    for field_name in _MUTABLE_SESSION_FIELDS:
        merged[field_name] = source[field_name]
    merged["created_at"] = min(
        str(source["created_at"] or target["created_at"]),
        str(target["created_at"] or source["created_at"]),
    )
    return merged


def _identity_mismatches(
    source: dict[str, Any],
    target: dict[str, Any],
) -> list[dict[str, str]]:
    mismatches: list[dict[str, str]] = []
    for field_name in _IDENTITY_FIELDS:
        source_value = str(source[field_name] or "").strip()
        target_value = str(target[field_name] or "").strip()
        if source_value and target_value and source_value != target_value:
            mismatches.append(
                {
                    "field": field_name,
                    "source": source_value,
                    "target": target_value,
                }
            )
    return mismatches


def _natural_identity(row: dict[str, Any]) -> tuple[str, str, str, str] | None:
    values = tuple(str(row[field_name] or "").strip() for field_name in _IDENTITY_FIELDS)
    return values if values[2] else None


def _message_signature(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row["session_id"]),
        *_message_content_signature(row),
    )


def _message_content_signature(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(row[field_name] or "")
        for field_name in (
            "sender",
            "text",
            "raw_text",
            "sent_at",
            "platform_message_id",
            "message_hash",
        )
    )


def _is_newer(source_value: str, target_value: str) -> bool:
    return source_value > target_value


def _load_rows(
    database: Path,
    table: str,
    columns: tuple[str, ...],
) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        return _rows_from_connection(connection, table, columns)


def _rows_from_connection(
    connection: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows = connection.execute(f"SELECT {', '.join(columns)} FROM {table}")
    return [dict(row) for row in rows]


def _assert_delta_schema(connection: sqlite3.Connection) -> None:
    _assert_columns(connection, "conversation_sessions", set(SESSION_COLUMNS))
    _assert_columns(connection, "conversation_messages", set(MESSAGE_COLUMNS))
    _assert_columns(connection, "conversation_sync_metadata", {"key", "value"})


def _assert_target_schema(connection: sqlite3.Connection) -> None:
    _assert_columns(connection, "resumes", {"id", "linked_session_id"})
    _assert_columns(connection, "conversation_sessions", set(SESSION_COLUMNS))
    _assert_columns(connection, "conversation_messages", set(MESSAGE_COLUMNS))


def _assert_columns(
    connection: sqlite3.Connection,
    table: str,
    expected: set[str],
) -> None:
    actual = {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
    }
    missing = sorted(expected - actual)
    if missing:
        raise RuntimeError(f"conversation_sync_schema_missing: {table}: {missing}")


def _linked_resume_count(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM resumes AS resumes
        JOIN conversation_sessions AS sessions ON sessions.id = resumes.linked_session_id
        """
    ).fetchone()
    return int(row[0])


def _linked_resume_session_ids(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT linked_session_id FROM resumes WHERE COALESCE(linked_session_id, '') <> ''"
        )
    ]


def _backup_target(target: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    backup = backup_dir / f"resumes_before_conversation_sync_{timestamp}.sqlite"
    source_uri = target.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as source_connection:
        with closing(sqlite3.connect(backup)) as backup_connection:
            source_connection.backup(backup_connection)
    if _quick_check(backup) != "ok":
        backup.unlink(missing_ok=True)
        raise RuntimeError("conversation_sync_backup_quick_check_failed")
    return backup


def _quick_check(database: Path) -> str:
    with closing(sqlite3.connect(database)) as connection:
        return str(connection.execute("PRAGMA quick_check").fetchone()[0])


def _foreign_key_violation_count(database: Path) -> int:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        return len(list(connection.execute("PRAGMA foreign_key_check")))


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _insert_sql(table: str, columns: tuple[str, ...]) -> str:
    placeholders = ", ".join("?" for _ in columns)
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"


def _row_values(row: dict[str, Any], columns: tuple[str, ...]) -> tuple[Any, ...]:
    return tuple(row[column] for column in columns)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is None:
        return
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--delta", required=True)
    parser.add_argument("--manifest", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--backup-dir", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    report = run_sync(
        ConversationSyncConfig(
            target_db=Path(args.target),
            delta_db=Path(args.delta),
            manifest_path=Path(args.manifest) if args.manifest else None,
            report_path=Path(args.report) if args.report else None,
            backup_dir=Path(args.backup_dir) if args.backup_dir else None,
            apply=args.apply,
            yes=args.yes,
        )
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
