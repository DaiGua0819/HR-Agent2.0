"""Safely remove empty legacy Feishu bot audit tables from the recruitment DB."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_TABLES = ("feishu_bot_turns", "feishu_bot_events")
LEGACY_TABLES_BY_CASEFOLD = {table.casefold(): table for table in LEGACY_TABLES}
EXPECTED_COLUMNS = {
    "feishu_bot_events": (
        ("event_id", "TEXT", 0, None, 1),
        ("message_id", "TEXT", 1, None, 0),
        ("sender_open_id", "TEXT", 1, None, 0),
        ("chat_id", "TEXT", 1, None, 0),
        ("chat_type", "TEXT", 1, "''", 0),
        ("message_type", "TEXT", 1, "''", 0),
        ("status", "TEXT", 1, "'received'", 0),
        ("response_message_id", "TEXT", 1, "''", 0),
        ("error", "TEXT", 1, "''", 0),
        ("received_at", "TEXT", 1, None, 0),
        ("started_at", "TEXT", 1, "''", 0),
        ("completed_at", "TEXT", 1, "''", 0),
    ),
    "feishu_bot_turns": (
        ("id", "TEXT", 0, None, 1),
        ("event_id", "TEXT", 1, None, 0),
        ("chat_id", "TEXT", 1, None, 0),
        ("sender_open_id", "TEXT", 1, None, 0),
        ("actor_name", "TEXT", 1, "''", 0),
        ("intent", "TEXT", 1, "''", 0),
        ("question", "TEXT", 1, "''", 0),
        ("response", "TEXT", 1, "''", 0),
        ("created_at", "TEXT", 1, None, 0),
    ),
}
EXPECTED_INDEXES = {
    "feishu_bot_events": {
        "idx_feishu_bot_events_sender": (
            0,
            0,
            (("sender_open_id", 0, "BINARY"), ("received_at", 1, "BINARY")),
        ),
        "idx_feishu_bot_events_status": (
            0,
            0,
            (("status", 0, "BINARY"), ("received_at", 1, "BINARY")),
        ),
    },
    "feishu_bot_turns": {
        "idx_feishu_bot_turns_context": (
            0,
            0,
            (
                ("chat_id", 0, "BINARY"),
                ("sender_open_id", 0, "BINARY"),
                ("created_at", 1, "BINARY"),
            ),
        )
    },
}
EXPECTED_AUTO_INDEXES = {
    "feishu_bot_events": {
        ("pk", 1, 0, (("event_id", 0, "BINARY"),)),
        ("u", 1, 0, (("message_id", 0, "BINARY"),)),
    },
    "feishu_bot_turns": {("pk", 1, 0, (("id", 0, "BINARY"),))},
}
EXPECTED_FOREIGN_KEYS = {
    "feishu_bot_events": set(),
    "feishu_bot_turns": {
        (
            "feishu_bot_events",
            "event_id",
            "event_id",
            "NO ACTION",
            "CASCADE",
            "NONE",
        )
    },
}
EXPECTED_TABLE_SQL = {
    "feishu_bot_events": """
        CREATE TABLE feishu_bot_events (
          event_id TEXT PRIMARY KEY,
          message_id TEXT NOT NULL UNIQUE,
          sender_open_id TEXT NOT NULL,
          chat_id TEXT NOT NULL,
          chat_type TEXT NOT NULL DEFAULT '',
          message_type TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'received',
          response_message_id TEXT NOT NULL DEFAULT '',
          error TEXT NOT NULL DEFAULT '',
          received_at TEXT NOT NULL,
          started_at TEXT NOT NULL DEFAULT '',
          completed_at TEXT NOT NULL DEFAULT ''
        )
    """,
    "feishu_bot_turns": """
        CREATE TABLE feishu_bot_turns (
          id TEXT PRIMARY KEY,
          event_id TEXT NOT NULL,
          chat_id TEXT NOT NULL,
          sender_open_id TEXT NOT NULL,
          actor_name TEXT NOT NULL DEFAULT '',
          intent TEXT NOT NULL DEFAULT '',
          question TEXT NOT NULL DEFAULT '',
          response TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          FOREIGN KEY(event_id) REFERENCES feishu_bot_events(event_id) ON DELETE CASCADE
        )
    """,
}
EXPECTED_INDEX_SQL = {
    "feishu_bot_events": {
        "idx_feishu_bot_events_sender": """
            CREATE INDEX idx_feishu_bot_events_sender
              ON feishu_bot_events(sender_open_id, received_at DESC)
        """,
        "idx_feishu_bot_events_status": """
            CREATE INDEX idx_feishu_bot_events_status
              ON feishu_bot_events(status, received_at DESC)
        """,
    },
    "feishu_bot_turns": {
        "idx_feishu_bot_turns_context": """
            CREATE INDEX idx_feishu_bot_turns_context
              ON feishu_bot_turns(chat_id, sender_open_id, created_at DESC)
        """,
    },
}


def cleanup_legacy_tables(
    database_path: str | Path,
    *,
    apply: bool = False,
    backup_dir: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(database_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"database_not_found:{path}")

    with sqlite3.connect(path, timeout=5) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        snapshot = _validated_snapshot(connection)
        if not snapshot:
            return {
                "status": "not_needed",
                "applied": False,
                "databasePath": str(path),
                "backupPath": "",
                "quickCheck": connection.execute("PRAGMA quick_check").fetchone()[0],
            }
        if not apply:
            return {
                "status": "ready",
                "applied": False,
                "databasePath": str(path),
                "backupPath": "",
                "tables": snapshot,
            }

        connection.execute("BEGIN IMMEDIATE")
        try:
            snapshot = _validated_snapshot(connection)
            if not snapshot:
                connection.rollback()
                return _not_needed_result(path, connection)
            destination = _backup_path(path, backup_dir)
            _write_json_atomic(
                destination,
                {
                    "databasePath": str(path),
                    "createdAt": datetime.now(UTC).isoformat(),
                    "tables": snapshot,
                },
            )
            for table in LEGACY_TABLES:
                connection.execute(f'DROP TABLE "{table}"')
            remaining = _present_legacy_tables(connection)
            if remaining:
                raise RuntimeError(
                    f"legacy_feishu_bot_cleanup_incomplete:{','.join(remaining)}"
                )
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            if quick_check != "ok":
                raise RuntimeError(f"legacy_feishu_bot_cleanup_check_failed:{quick_check}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return {
            "status": "cleaned",
            "applied": True,
            "databasePath": str(path),
            "backupPath": str(destination),
            "quickCheck": quick_check,
        }


def _validated_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    present = _present_legacy_tables(connection)
    if not present:
        return {}
    if set(present) != set(LEGACY_TABLES):
        raise RuntimeError("legacy_feishu_bot_schema_unexpected:partial_tables")
    dependencies = _inbound_dependencies(connection)
    if dependencies:
        dependency = dependencies[0]
        raise RuntimeError(
            "legacy_feishu_bot_schema_in_use:"
            f"{dependency['sourceTable']}:{dependency['sourceColumn']}->"
            f"{dependency['targetTable']}"
        )

    snapshot: dict[str, Any] = {}
    for table in LEGACY_TABLES:
        table_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        table_sql = str(table_row["sql"] or "")
        if _normalized_sql(table_sql) != _normalized_sql(EXPECTED_TABLE_SQL[table]):
            raise RuntimeError(f"legacy_feishu_bot_schema_unexpected:{table}:sql")
        columns = tuple(
            (
                str(row["name"]),
                str(row["type"]).upper(),
                int(row["notnull"]),
                str(row["dflt_value"]) if row["dflt_value"] is not None else None,
                int(row["pk"]),
            )
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        )
        if columns != EXPECTED_COLUMNS[table]:
            raise RuntimeError(f"legacy_feishu_bot_schema_unexpected:{table}:columns")
        objects = list(
            connection.execute(
                """
                SELECT type, name, sql
                FROM sqlite_master
                WHERE tbl_name = ? AND type IN ('index', 'trigger')
                ORDER BY type, name
                """,
                (table,),
            )
        )
        triggers = [row for row in objects if row["type"] == "trigger"]
        explicit_index_sql = {
            str(row["name"]): _normalized_sql(str(row["sql"] or ""))
            for row in objects
            if row["type"] == "index"
            and not str(row["name"]).startswith("sqlite_autoindex_")
        }
        expected_index_sql = {
            name: _normalized_sql(sql)
            for name, sql in EXPECTED_INDEX_SQL[table].items()
        }
        index_rows = list(connection.execute(f'PRAGMA index_list("{table}")'))
        explicit_indexes = {
            str(row["name"]): (
                int(row["unique"]),
                int(row["partial"]),
                _index_key_columns(connection, str(row["name"])),
            )
            for row in index_rows
            if str(row["origin"]) == "c"
        }
        auto_indexes = {
            (
                str(row["origin"]),
                int(row["unique"]),
                int(row["partial"]),
                _index_key_columns(connection, str(row["name"])),
            )
            for row in index_rows
            if str(row["origin"]) != "c"
        }
        foreign_keys = {
            (
                str(row["table"]),
                str(row["from"]),
                str(row["to"]),
                str(row["on_update"]),
                str(row["on_delete"]),
                str(row["match"]),
            )
            for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
        }
        if (
            triggers
            or explicit_index_sql != expected_index_sql
            or explicit_indexes != EXPECTED_INDEXES[table]
            or auto_indexes != EXPECTED_AUTO_INDEXES[table]
            or foreign_keys != EXPECTED_FOREIGN_KEYS[table]
        ):
            raise RuntimeError(f"legacy_feishu_bot_schema_unexpected:{table}:objects")
        row_count = int(
            connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        )
        if row_count:
            raise RuntimeError(f"legacy_feishu_bot_tables_not_empty:{table}:{row_count}")
        snapshot[table] = {
            "rowCount": row_count,
            "sql": table_sql,
            "objects": [
                {
                    "type": str(row["type"]),
                    "name": str(row["name"]),
                    "sql": str(row["sql"] or ""),
                }
                for row in objects
            ],
        }
    return snapshot


def _index_key_columns(
    connection: sqlite3.Connection,
    index_name: str,
) -> tuple[tuple[str, int, str], ...]:
    escaped = index_name.replace('"', '""')
    return tuple(
        (str(row["name"]), int(row["desc"]), str(row["coll"] or ""))
        for row in connection.execute(f'PRAGMA index_xinfo("{escaped}")')
        if int(row["key"]) == 1
    )


def _inbound_dependencies(connection: sqlite3.Connection) -> list[dict[str, str]]:
    dependencies: list[dict[str, str]] = []
    tables = [
        name
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            ORDER BY name
            """
        )
        if not (name := str(row["name"])).casefold().startswith("sqlite_")
        and name.casefold() not in LEGACY_TABLES_BY_CASEFOLD
    ]
    for table in tables:
        escaped = table.replace('"', '""')
        for row in connection.execute(f'PRAGMA foreign_key_list("{escaped}")'):
            target = str(row["table"])
            target_key = target.casefold()
            if target_key in LEGACY_TABLES_BY_CASEFOLD:
                dependencies.append(
                    {
                        "sourceTable": table,
                        "sourceColumn": str(row["from"]),
                        "targetTable": LEGACY_TABLES_BY_CASEFOLD[target_key],
                    }
                )
    for row in connection.execute(
        """
        SELECT type, name, sql
        FROM sqlite_master
        WHERE type IN ('view', 'trigger') AND sql IS NOT NULL
        ORDER BY type, name
        """
    ):
        sql = str(row["sql"])
        for target in LEGACY_TABLES:
            if re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(target)}(?![A-Za-z0-9_])",
                sql,
                flags=re.IGNORECASE,
            ):
                dependencies.append(
                    {
                        "sourceTable": f"{row['type']}:{row['name']}",
                        "sourceColumn": "sql",
                        "targetTable": target,
                    }
                )
    return dependencies


def _normalized_sql(value: str) -> str:
    return " ".join(value.strip().rstrip(";").split())


def _present_legacy_tables(connection: sqlite3.Connection) -> list[str]:
    return [
        table
        for table in LEGACY_TABLES
        if connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND lower(name) = lower(?)
            """,
            (table,),
        ).fetchone()
        is not None
    ]


def _not_needed_result(
    database_path: Path,
    connection: sqlite3.Connection,
) -> dict[str, Any]:
    return {
        "status": "not_needed",
        "applied": False,
        "databasePath": str(database_path),
        "backupPath": "",
        "quickCheck": connection.execute("PRAGMA quick_check").fetchone()[0],
    }


def _backup_path(database_path: Path, backup_dir: str | Path | None) -> Path:
    directory = (
        Path(backup_dir).resolve()
        if backup_dir is not None
        else database_path.parent / "backups"
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return directory / f"legacy-feishu-bot-schema-{timestamp}.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        default=str(PROJECT_ROOT / "data" / "resumes.sqlite"),
    )
    parser.add_argument("--backup-dir", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = cleanup_legacy_tables(
        args.database,
        apply=args.apply,
        backup_dir=args.backup_dir or None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
