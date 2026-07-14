"""Export conversation history into a small, self-validating SQLite delta package."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FORMAT_VERSION = "conversation-delta-v1"
SESSION_COLUMNS = (
    "id",
    "platform",
    "owner",
    "candidate_name",
    "position",
    "applied_position",
    "platform_conversation_id",
    "label",
    "current_stage",
    "next_action",
    "recent_messages_fingerprint",
    "identity_confidence",
    "identity_warnings",
    "last_seen_at",
    "created_at",
    "updated_at",
)
MESSAGE_COLUMNS = (
    "id",
    "session_id",
    "sender",
    "text",
    "raw_text",
    "sent_at",
    "platform_message_id",
    "message_hash",
    "created_at",
)
DELTA_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE conversation_sessions (
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  owner TEXT NOT NULL,
  candidate_name TEXT NOT NULL DEFAULT '',
  position TEXT NOT NULL DEFAULT '',
  applied_position TEXT NOT NULL DEFAULT '',
  platform_conversation_id TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL DEFAULT '',
  current_stage TEXT NOT NULL DEFAULT '',
  next_action TEXT NOT NULL DEFAULT '',
  recent_messages_fingerprint TEXT NOT NULL DEFAULT '',
  identity_confidence TEXT NOT NULL DEFAULT '',
  identity_warnings TEXT NOT NULL DEFAULT '[]',
  last_seen_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_conversation_sessions_platform_identity
  ON conversation_sessions(platform, owner, platform_conversation_id, position)
  WHERE platform_conversation_id <> '';

CREATE TABLE conversation_messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  sender TEXT NOT NULL,
  text TEXT NOT NULL,
  raw_text TEXT NOT NULL DEFAULT '',
  sent_at TEXT NOT NULL DEFAULT '',
  platform_message_id TEXT NOT NULL DEFAULT '',
  message_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES conversation_sessions(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_conversation_messages_hash
  ON conversation_messages(session_id, message_hash);
CREATE INDEX idx_conversation_messages_session
  ON conversation_messages(session_id, created_at);

CREATE TABLE conversation_sync_metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def export_conversation_delta(
    source_db: str | Path,
    output_db: str | Path,
    *,
    manifest_path: str | Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    source = Path(source_db)
    output = Path(output_db)
    manifest = Path(manifest_path) if manifest_path else output.with_suffix(".manifest.json")
    sha256_path = output.with_suffix(".sha256")
    if not source.is_file():
        raise FileNotFoundError(f"conversation_source_not_found: {source}")
    if source.resolve() == output.resolve():
        raise ValueError("conversation_delta_must_not_replace_source")
    for path in (output, manifest, sha256_path):
        if path.exists() and not overwrite:
            raise FileExistsError(f"conversation_delta_output_exists: {path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    for path in (output, manifest, sha256_path):
        if path.exists():
            path.unlink()

    generated_at = datetime.now(UTC).isoformat()
    source_uri = source.resolve().as_uri() + "?mode=ro"
    try:
        with closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as source_connection:
            source_connection.row_factory = sqlite3.Row
            _assert_source_schema(source_connection)
            source_quick_check = str(
                source_connection.execute("PRAGMA quick_check").fetchone()[0]
            )
            if source_quick_check != "ok":
                raise RuntimeError(f"conversation_source_quick_check_failed: {source_quick_check}")
            source_connection.execute("BEGIN")
            sessions = list(
                source_connection.execute(
                    f"SELECT {', '.join(SESSION_COLUMNS)} FROM conversation_sessions"
                )
            )
            messages = list(
                source_connection.execute(
                    f"SELECT {', '.join(MESSAGE_COLUMNS)} FROM conversation_messages"
                )
            )
            source_connection.rollback()

        with closing(sqlite3.connect(output)) as delta_connection:
            delta_connection.executescript(DELTA_SCHEMA)
            delta_connection.executemany(
                _insert_sql("conversation_sessions", SESSION_COLUMNS),
                [tuple(row[column] for column in SESSION_COLUMNS) for row in sessions],
            )
            delta_connection.executemany(
                _insert_sql("conversation_messages", MESSAGE_COLUMNS),
                [tuple(row[column] for column in MESSAGE_COLUMNS) for row in messages],
            )
            metadata = {
                "formatVersion": FORMAT_VERSION,
                "generatedAt": generated_at,
                "sourceDatabase": str(source.resolve()),
                "sessionCount": str(len(sessions)),
                "messageCount": str(len(messages)),
            }
            delta_connection.executemany(
                "INSERT INTO conversation_sync_metadata (key, value) VALUES (?, ?)",
                metadata.items(),
            )
            delta_connection.commit()
            delta_connection.execute("VACUUM")

        quick_check = _quick_check(output)
        orphan_messages = _orphan_count(output)
        if quick_check != "ok" or orphan_messages:
            raise RuntimeError(
                "conversation_delta_validation_failed: "
                f"quick_check={quick_check}, orphan_messages={orphan_messages}"
            )
        digest = _sha256(output)
        platforms = Counter(str(row["platform"] or "unknown") for row in sessions)
        owners = Counter(str(row["owner"] or "unknown") for row in sessions)
        manifest_payload: dict[str, Any] = {
            "formatVersion": FORMAT_VERSION,
            "generatedAt": generated_at,
            "sourceDatabase": str(source.resolve()),
            "deltaDatabase": str(output.resolve()),
            "sessionCount": len(sessions),
            "messageCount": len(messages),
            "orphanMessages": orphan_messages,
            "quickCheck": quick_check,
            "platforms": dict(sorted(platforms.items())),
            "owners": dict(sorted(owners.items())),
            "fileSize": output.stat().st_size,
            "sha256": digest,
        }
        manifest.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        sha256_path.write_text(digest + "\n", encoding="ascii")
        return {
            **manifest_payload,
            "manifestPath": str(manifest),
            "sha256Path": str(sha256_path),
        }
    except Exception:
        if output.exists():
            output.unlink()
        raise


def _assert_source_schema(connection: sqlite3.Connection) -> None:
    for table, expected in (
        ("conversation_sessions", set(SESSION_COLUMNS)),
        ("conversation_messages", set(MESSAGE_COLUMNS)),
    ):
        actual = {
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
        }
        missing = sorted(expected - actual)
        if missing:
            raise RuntimeError(f"conversation_source_schema_missing: {table}: {missing}")


def _insert_sql(table: str, columns: tuple[str, ...]) -> str:
    placeholders = ", ".join("?" for _ in columns)
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"


def _quick_check(database: Path) -> str:
    with closing(sqlite3.connect(database)) as connection:
        return str(connection.execute("PRAGMA quick_check").fetchone()[0])


def _orphan_count(database: Path) -> int:
    with closing(sqlite3.connect(database)) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM conversation_messages AS messages
            LEFT JOIN conversation_sessions AS sessions ON sessions.id = messages.session_id
            WHERE sessions.id IS NULL
            """
        ).fetchone()
    return int(row[0])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", default="")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    report = export_conversation_delta(
        args.source,
        args.output,
        manifest_path=args.manifest or None,
        overwrite=args.overwrite,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
