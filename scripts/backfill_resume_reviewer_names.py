"""Backfill persisted reviewer names without guessing user identities."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.engine import connect, run_migrations  # noqa: E402
from app.settings import load_settings  # noqa: E402


def backfill_reviewer_names(
    database_path: str | Path,
    *,
    identities: dict[str, str],
    apply: bool = False,
) -> dict[str, object]:
    """Report or fill blank ``user_name`` values for exact user IDs."""

    database = Path(database_path)
    normalized = _normalized_identities(identities)
    if apply:
        run_migrations(database)

    with connect(database, read_only=not apply) as connection:
        rows = connection.execute(
            """
            SELECT user_id, user_name, decision
            FROM resume_review_states
            WHERE decision != 'undecided'
            ORDER BY user_id, resume_id
            """
        ).fetchall()
        identity_counts = {
            user_id: {
                "name": name,
                "blankRows": sum(
                    1
                    for row in rows
                    if row["user_id"] == user_id and not str(row["user_name"] or "").strip()
                ),
                "namedRows": sum(
                    1
                    for row in rows
                    if row["user_id"] == user_id and str(row["user_name"] or "").strip()
                ),
            }
            for user_id, name in normalized.items()
        }
        matched_rows = sum(int(item["blankRows"]) for item in identity_counts.values())
        preserved_named_rows = sum(int(item["namedRows"]) for item in identity_counts.values())
        unresolved = sorted(
            {
                str(row["user_id"])
                for row in rows
                if row["decision"] != "undecided"
                and not str(row["user_name"] or "").strip()
                and str(row["user_id"]) not in normalized
            }
        )
        updated_rows = 0
        if apply:
            connection.execute("BEGIN IMMEDIATE")
            for user_id, name in normalized.items():
                cursor = connection.execute(
                    """
                    UPDATE resume_review_states
                    SET user_name = ?
                    WHERE user_id = ?
                      AND decision != 'undecided'
                      AND TRIM(COALESCE(user_name, '')) = ''
                    """,
                    (name, user_id),
                )
                updated_rows += cursor.rowcount
            connection.commit()

    return {
        "database": str(database),
        "apply": apply,
        "identityCounts": identity_counts,
        "matchedRows": matched_rows,
        "preservedNamedRows": preserved_named_rows,
        "updatedRows": updated_rows,
        "unresolvedUserIds": unresolved,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill exact reviewer ID-to-name mappings.")
    parser.add_argument(
        "--database",
        default="",
        help="SQLite path; defaults to application settings",
    )
    parser.add_argument(
        "--identity",
        action="append",
        default=[],
        metavar="USER_ID=NAME",
        help="Exact reviewer identity mapping; repeat for multiple users",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes after reviewing dry-run",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database = Path(args.database) if args.database else load_settings().resolved_database_path
    identities = _parse_identity_args(args.identity)
    report = backfill_reviewer_names(database, identities=identities, apply=bool(args.apply))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


def _parse_identity_args(values: list[str]) -> dict[str, str]:
    identities: dict[str, str] = {}
    for value in values:
        user_id, separator, name = value.partition("=")
        user_id = user_id.strip()
        name = name.strip()
        if not separator or not user_id or not name:
            raise SystemExit(f"invalid_identity_mapping:{value}")
        identities[user_id] = name
    return identities


def _normalized_identities(identities: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for user_id, name in identities.items():
        clean_user_id = str(user_id or "").strip()
        clean_name = str(name or "").strip()
        if not clean_user_id or not clean_name:
            raise ValueError("identity_mapping_requires_user_id_and_name")
        normalized[clean_user_id] = clean_name
    return normalized


if __name__ == "__main__":  # pragma: no cover - CLI wrapper
    raise SystemExit(main())
