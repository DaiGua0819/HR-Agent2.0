"""Sync legacy 8080 resume SQLite rows and PDF files into the preview DB."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import tempfile
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "app" / "db" / "schema.sql"
_BASE_COLUMNS = {"id", "payload", "phone_key", "job_type", "match_score", "updated_at"}
_INSERT_SQL = """
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
"""


@dataclass(frozen=True)
class SyncConfig:
    legacy_db: Path
    legacy_upload_dir: Path
    target_db: Path
    target_upload_dir: Path
    mode: str = "replace"
    limit: int | None = None
    apply: bool = False
    yes: bool = False


def run_sync(config: SyncConfig) -> dict[str, Any]:
    """Run a dry-run or apply sync and return a JSON-serializable report."""

    _validate_config(config)
    report = _empty_report(config)
    with tempfile.TemporaryDirectory(prefix="hr-agent-legacy-sync-") as temp_dir:
        snapshot = Path(temp_dir) / "legacy_snapshot.sqlite"
        _backup_sqlite(config.legacy_db, snapshot)
        report["legacyQuickCheck"] = _quick_check(snapshot)
        _assert_legacy_schema(snapshot)
        rows = _load_legacy_rows(snapshot, config.limit)
        existing_ids = _target_ids(config.target_db) if config.target_db.exists() else set()
        report.update(_summarize_rows(rows))
        report["scanned"] = len(rows)
        prepared = _prepare_rows(rows, config, existing_ids, report)
        report["wouldImport"] = len(prepared)
        if not config.apply:
            return report
        if not config.yes:
            raise RuntimeError("apply_requires_yes")
        backup_path = _backup_target_if_exists(config.target_db)
        report["targetBackupPath"] = str(backup_path) if backup_path else ""
        manifest_path = _write_apply_manifest(config, rows, prepared, backup_path)
        report["manifestPath"] = str(manifest_path)
        _apply_rows(config, prepared, report)
        report["targetQuickCheck"] = _quick_check(config.target_db)
        return report


def _validate_config(config: SyncConfig) -> None:
    if config.mode not in {"replace", "merge"}:
        raise ValueError("mode_must_be_replace_or_merge")
    if not config.legacy_db.exists():
        raise FileNotFoundError(f"legacy_db_not_found: {config.legacy_db}")
    if not config.legacy_upload_dir.exists():
        raise FileNotFoundError(f"legacy_upload_dir_not_found: {config.legacy_upload_dir}")
    if config.limit is not None and config.limit < 1:
        raise ValueError("limit_must_be_positive")


def _empty_report(config: SyncConfig) -> dict[str, Any]:
    return {
        "dryRun": not config.apply,
        "mode": config.mode,
        "legacyDb": str(config.legacy_db),
        "targetDb": str(config.target_db),
        "targetUploadDir": str(config.target_upload_dir),
        "legacyQuickCheck": "",
        "targetQuickCheck": "",
        "targetBackupPath": "",
        "manifestPath": "",
        "scanned": 0,
        "wouldImport": 0,
        "imported": 0,
        "skippedExisting": 0,
        "pdfExisting": 0,
        "pdfMissing": 0,
        "pdfCopied": 0,
        "replacedTarget": False,
        "jobTypes": {},
        "platforms": {},
        "owners": {},
        "missingPdfSamples": [],
    }


def _backup_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    uri = source.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as source_connection:
        with closing(sqlite3.connect(destination)) as destination_connection:
            source_connection.backup(destination_connection)


def _quick_check(database: Path) -> str:
    with closing(sqlite3.connect(database)) as connection:
        return str(connection.execute("PRAGMA quick_check").fetchone()[0])


def _assert_legacy_schema(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(resumes)").fetchall()
        }
    missing = sorted(_BASE_COLUMNS - columns)
    if missing:
        raise RuntimeError(f"legacy_resumes_schema_missing_columns: {missing}")


def _load_legacy_rows(database: Path, limit: int | None) -> list[sqlite3.Row]:
    suffix = " ORDER BY updated_at DESC"
    params: tuple[Any, ...] = ()
    if limit is not None:
        suffix += " LIMIT ?"
        params = (limit,)
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        return list(connection.execute(f"SELECT * FROM resumes{suffix}", params).fetchall())


def _target_ids(database: Path) -> set[str]:
    try:
        with closing(sqlite3.connect(database)) as connection:
            return {str(row[0]) for row in connection.execute("SELECT id FROM resumes")}
    except sqlite3.Error:
        return set()


def _summarize_rows(rows: list[sqlite3.Row]) -> dict[str, dict[str, int]]:
    jobs: Counter[str] = Counter()
    platforms: Counter[str] = Counter()
    owners: Counter[str] = Counter()
    for row in rows:
        payload = _decode_payload(row)
        jobs[_first_text(row["job_type"], payload.get("jobType"), "unknown")] += 1
        platforms[
            _first_text(payload.get("platform"), payload.get("sourcePlatform"), "unknown")
        ] += 1
        owners[_first_text(payload.get("accountName"), payload.get("sourceName"), "unknown")] += 1
    return {
        "jobTypes": dict(jobs.most_common()),
        "platforms": dict(platforms.most_common()),
        "owners": dict(owners.most_common()),
    }


def _prepare_rows(
    rows: list[sqlite3.Row],
    config: SyncConfig,
    existing_ids: set[str],
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for row in rows:
        resume_id = str(row["id"])
        if config.mode == "merge" and resume_id in existing_ids:
            report["skippedExisting"] += 1
            continue
        payload = _decode_payload(row)
        source_pdf = _resolve_source_pdf(resume_id, payload, config.legacy_upload_dir)
        target_pdf = config.target_upload_dir / "legacy" / f"{resume_id}{_pdf_suffix(source_pdf)}"
        if source_pdf and source_pdf.is_file():
            report["pdfExisting"] += 1
            rewritten_payload = _rewrite_payload(payload, source_pdf, target_pdf)
        else:
            report["pdfMissing"] += 1
            rewritten_payload = dict(payload)
            if len(report["missingPdfSamples"]) < 10:
                report["missingPdfSamples"].append(resume_id)
            target_pdf = None
        prepared.append(
            {
                "row": row,
                "payload": rewritten_payload,
                "source_pdf": source_pdf,
                "target_pdf": target_pdf,
            }
        )
    return prepared


def _decode_payload(row: sqlite3.Row) -> dict[str, Any]:
    try:
        value = json.loads(row["payload"])
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {"value": value}


def _resolve_source_pdf(resume_id: str, payload: dict[str, Any], upload_dir: Path) -> Path | None:
    for key in ("pdfPath", "pdf_path", "filePath", "file_path", "sourceFilePath"):
        value = payload.get(key)
        if value:
            return Path(str(value))
    fallback = upload_dir / f"{resume_id}.pdf"
    return fallback if fallback.exists() else None


def _pdf_suffix(source_pdf: Path | None) -> str:
    if source_pdf and source_pdf.suffix:
        return source_pdf.suffix.lower()
    return ".pdf"


def _rewrite_payload(payload: dict[str, Any], source_pdf: Path, target_pdf: Path) -> dict[str, Any]:
    updated = dict(payload)
    original = str(payload.get("pdfPath") or payload.get("pdf_path") or source_pdf)
    updated.setdefault("legacyPdfPath", original)
    updated["pdfPath"] = str(target_pdf)
    updated["hasPdf"] = True
    return updated


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _backup_target_if_exists(target_db: Path) -> Path | None:
    if not target_db.exists():
        return None
    backup_dir = target_db.parent / "backups"
    backup_path = backup_dir / f"resumes_before_legacy_sync_{_timestamp()}.sqlite"
    _backup_sqlite(target_db, backup_path)
    return backup_path


def _write_apply_manifest(
    config: SyncConfig,
    rows: list[sqlite3.Row],
    prepared: list[dict[str, Any]],
    backup_path: Path | None,
) -> Path:
    backup_dir = config.target_db.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = backup_dir / f"legacy_sync_manifest_{_timestamp()}.json"
    manifest = {
        "createdAt": datetime.now().astimezone().isoformat(),
        "legacyDb": str(config.legacy_db),
        "targetDb": str(config.target_db),
        "targetBackupPath": str(backup_path or ""),
        "mode": config.mode,
        "scannedIds": [str(row["id"]) for row in rows],
        "importIds": [str(item["row"]["id"]) for item in prepared],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def _apply_rows(
    config: SyncConfig,
    prepared: list[dict[str, Any]],
    report: dict[str, Any],
) -> None:
    _run_target_migrations(config.target_db)
    config.target_upload_dir.joinpath("legacy").mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(config.target_db)) as connection:
        if config.mode == "replace":
            connection.execute("DELETE FROM resumes")
            report["replacedTarget"] = True
        for item in prepared:
            source_pdf = item["source_pdf"]
            target_pdf = item["target_pdf"]
            if source_pdf and target_pdf:
                shutil.copy2(source_pdf, target_pdf)
                report["pdfCopied"] += 1
            row = item["row"]
            payload = item["payload"]
            connection.execute(
                _INSERT_SQL,
                (
                    row["id"],
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    row["phone_key"],
                    row["job_type"],
                    row["match_score"],
                    row["updated_at"],
                    _first_text(payload.get("name"), payload.get("candidateName")),
                    "",
                    "",
                    "",
                    "",
                    "",
                ),
            )
            report["imported"] += 1
        connection.commit()


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def _run_target_migrations(target_db: Path) -> None:
    target_db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(target_db)) as connection:
        if SCHEMA_PATH.exists():
            connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        for column in (
            "parsed_name",
            "linked_session_id",
            "linked_platform",
            "linked_owner",
            "linked_platform_conversation_id",
            "source_artifact_id",
        ):
            _add_column_if_missing(connection, "resumes", column, "TEXT")
        connection.commit()


def _add_column_if_missing(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _default_config(args: argparse.Namespace) -> SyncConfig:
    legacy_db = (
        Path(args.legacy_db)
        if args.legacy_db
        else PROJECT_ROOT.parent / "patchwork-recruit-gpt" / "data" / "resumes.sqlite"
    )
    legacy_upload_dir = (
        Path(args.legacy_upload_dir) if args.legacy_upload_dir else legacy_db.parent / "uploads"
    )
    target_db = Path(args.target_db) if args.target_db else PROJECT_ROOT / "data" / "resumes.sqlite"
    target_upload_dir = (
        Path(args.target_upload_dir)
        if args.target_upload_dir
        else PROJECT_ROOT / "data" / "uploads"
    )
    return SyncConfig(
        legacy_db=legacy_db,
        legacy_upload_dir=legacy_upload_dir,
        target_db=target_db,
        target_upload_dir=target_upload_dir,
        mode=args.mode,
        limit=args.limit,
        apply=args.apply,
        yes=args.yes,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-db", default="")
    parser.add_argument("--legacy-upload-dir", default="")
    parser.add_argument("--target-db", default="")
    parser.add_argument("--target-upload-dir", default="")
    parser.add_argument("--mode", choices=["replace", "merge"], default="replace")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--yes", action="store_true")
    config = _default_config(parser.parse_args())
    report = run_sync(config)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
