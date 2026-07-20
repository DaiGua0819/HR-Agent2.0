"""Export and idempotently import daily recruitment monitoring events."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.domain.automation_monitoring.daily_projection import (  # noqa: E402
    CHINA_TZ,
    DailyProjectionExport,
    build_daily_projections,
)
from app.domain.automation_monitoring.models import AutomationContactEvent  # noqa: E402
from app.domain.automation_monitoring.repository import (  # noqa: E402
    AutomationMonitoringRepository,
)

PACKAGE_VERSION = 2
PACKAGE_TIMEZONE = "Asia/Shanghai"


def build_export_package(
    exported: DailyProjectionExport,
    *,
    start_date: date,
    end_date: date,
    generated_at: str | None = None,
    artifacts: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "version": PACKAGE_VERSION,
        "timezone": PACKAGE_TIMEZONE,
        "generatedAt": generated_at or datetime.now(UTC).isoformat(),
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "coverage": dict(exported.coverage),
        "summary": dict(exported.summary),
        "artifacts": list(artifacts or []),
        "events": [
            event.model_dump(by_alias=True, mode="json") for event in exported.events
        ],
    }


def export_resume_artifacts(
    *,
    database_path: str | Path,
    events: list[AutomationContactEvent],
    files_dir: str | Path,
) -> list[dict[str, object]]:
    file_hashes = sorted(
        {
            event.resume_file_hash
            for event in events
            if event.resume_acquired
            and event.platform != "boss"
            and event.resume_file_hash
        }
    )
    if not file_hashes:
        return []
    rows_by_hash: dict[str, sqlite3.Row] = {}
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        for offset in range(0, len(file_hashes), 500):
            chunk = file_hashes[offset : offset + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                "SELECT * FROM resume_artifacts "
                f"WHERE file_hash IN ({placeholders}) "
                "ORDER BY updated_at DESC, id DESC",
                chunk,
            ).fetchall()
            for row in rows:
                rows_by_hash.setdefault(str(row["file_hash"]), row)

    output_dir = Path(files_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, object]] = []
    for file_hash in file_hashes:
        row = rows_by_hash.get(file_hash)
        if row is None:
            raise ValueError(f"resume artifact missing for file hash: {file_hash}")
        source = Path(str(row["file_path"] or ""))
        if not source.is_file():
            raise ValueError(f"resume artifact file missing: {source}")
        actual_hash = _file_sha256(source)
        if actual_hash != file_hash:
            raise ValueError(
                f"resume artifact hash mismatch: expected {file_hash}, got {actual_hash}"
            )
        bundle_name = f"{file_hash}{source.suffix.lower()}"
        destination = output_dir / bundle_name
        if not destination.is_file() or _file_sha256(destination) != file_hash:
            shutil.copy2(source, destination)
        artifacts.append(
            {
                "id": str(row["id"]),
                "sessionId": str(row["session_id"]),
                "platform": str(row["platform"]),
                "owner": str(row["owner"]),
                "platformConversationId": str(row["platform_conversation_id"]),
                "candidateName": str(row["candidate_name_from_platform"]),
                "position": str(row["position"]),
                "fileHash": file_hash,
                "bundleName": bundle_name,
                "fileSize": destination.stat().st_size,
                "sourceKind": str(row["source_kind"]),
                "parseStatus": str(row["parse_status"]),
                "parsedName": str(row["parsed_name"]),
                "resumeId": str(row["resume_id"]),
                "error": str(row["error"]),
                "createdAt": str(row["created_at"]),
                "updatedAt": str(row["updated_at"]),
            }
        )
    return artifacts


def package_sha256(package: dict[str, object]) -> str:
    canonical = json.dumps(
        package,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_package(package: dict[str, object]) -> list[AutomationContactEvent]:
    if int(package.get("version") or 0) != PACKAGE_VERSION:
        raise ValueError("unsupported package version")
    if str(package.get("timezone") or "") != PACKAGE_TIMEZONE:
        raise ValueError("unsupported package timezone")
    start_date = _date_value(package.get("startDate"), "startDate")
    end_date = _date_value(package.get("endDate"), "endDate")
    if start_date > end_date:
        raise ValueError("package startDate must not be after endDate")
    raw_events = package.get("events")
    if not isinstance(raw_events, list):
        raise ValueError("package events must be a list")
    if not isinstance(package.get("artifacts"), list):
        raise ValueError("package artifacts must be a list")

    by_id: dict[str, tuple[str, AutomationContactEvent]] = {}
    for raw_event in raw_events:
        event = AutomationContactEvent.model_validate(raw_event)
        event_day = _event_day(event)
        if event_day < start_date or event_day > end_date:
            raise ValueError(f"event outside package date range: {event.id}")
        fingerprint = json.dumps(
            event.model_dump(by_alias=True, mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        existing = by_id.get(event.id)
        if existing is not None and existing[0] != fingerprint:
            raise ValueError(f"conflicting duplicate event id: {event.id}")
        by_id[event.id] = (fingerprint, event)
    return [item[1] for item in by_id.values()]


def import_package(
    *,
    database_path: str | Path,
    package: dict[str, object],
    expected_sha256: str,
    files_dir: str | Path | None = None,
    apply: bool = False,
) -> dict[str, object]:
    actual_sha256 = package_sha256(package)
    if actual_sha256 != expected_sha256.strip().lower():
        raise ValueError(
            f"package sha256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )
    events = validate_package(package)
    artifacts = _validate_artifact_bundle(package, files_dir=files_dir)
    applied = 0
    applied_artifacts = 0
    if apply:
        repository = AutomationMonitoringRepository(database_path)
        applied_artifacts = _import_artifacts(
            database_path=database_path,
            artifacts=artifacts,
            files_dir=Path(files_dir) if files_dir is not None else None,
        )
        applied = repository.upsert_events(events)
    return {
        "validated": len(events),
        "validatedArtifacts": len(artifacts),
        "applied": applied,
        "appliedArtifacts": applied_artifacts,
        "dryRun": not apply,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="export daily events")
    export_parser.add_argument("--database", type=Path, required=True)
    export_parser.add_argument("--runs", type=Path, required=True)
    export_parser.add_argument("--end-date", type=date.fromisoformat)
    export_parser.add_argument("--days", type=int, default=7)
    export_parser.add_argument("--output", type=Path)
    export_parser.add_argument("--files-dir", type=Path)

    import_parser = subparsers.add_parser("import", help="validate or import a package")
    import_parser.add_argument("--database", type=Path, required=True)
    import_parser.add_argument("--input", type=Path, required=True)
    import_parser.add_argument("--expected-sha256", required=True)
    import_parser.add_argument("--files-dir", type=Path)
    import_parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "export":
        if args.days < 1:
            raise ValueError("--days must be at least 1")
        end_date = args.end_date or datetime.now(CHINA_TZ).date()
        start_date = end_date - timedelta(days=args.days - 1)
        exported = build_daily_projections(
            database_path=args.database,
            run_dir=args.runs,
            start_date=start_date,
            end_date=end_date,
        )
        files_dir = args.files_dir
        if files_dir is None and args.output is not None:
            files_dir = args.output.with_name(f"{args.output.stem}-files")
        artifacts = (
            export_resume_artifacts(
                database_path=args.database,
                events=exported.events,
                files_dir=files_dir,
            )
            if files_dir is not None
            else []
        )
        package = build_export_package(
            exported,
            start_date=start_date,
            end_date=end_date,
            artifacts=artifacts,
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(package, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(
            json.dumps(
                {
                    "output": str(args.output or ""),
                    "sha256": package_sha256(package),
                    "startDate": package["startDate"],
                    "endDate": package["endDate"],
                    "coverage": package["coverage"],
                    "summary": package["summary"],
                    "artifacts": len(artifacts),
                    "filesDir": str(files_dir or ""),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    package = _load_package(args.input)
    result = import_package(
        database_path=args.database,
        package=package,
        expected_sha256=str(args.expected_sha256),
        files_dir=args.files_dir,
        apply=bool(args.apply),
    )
    print(
        json.dumps(
            {**result, "sha256": package_sha256(package)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _validate_artifact_bundle(
    package: dict[str, object],
    *,
    files_dir: str | Path | None,
) -> list[dict[str, object]]:
    raw_artifacts = package.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise ValueError("package artifacts must be a list")
    if not raw_artifacts:
        return []
    if files_dir is None:
        raise ValueError("package artifact files directory is required")
    root = Path(files_dir)
    validated: list[dict[str, object]] = []
    seen_hashes: set[str] = set()
    for raw_artifact in raw_artifacts:
        if not isinstance(raw_artifact, dict):
            raise ValueError("package artifact must be an object")
        artifact = dict(raw_artifact)
        artifact_id = str(artifact.get("id") or "").strip()
        file_hash = str(artifact.get("fileHash") or "").strip().lower()
        bundle_name = str(artifact.get("bundleName") or "").strip()
        platform = str(artifact.get("platform") or "").strip()
        if not artifact_id or not platform:
            raise ValueError("package artifact identity is incomplete")
        if len(file_hash) != 64 or any(char not in "0123456789abcdef" for char in file_hash):
            raise ValueError(f"invalid package artifact hash: {file_hash}")
        if file_hash in seen_hashes:
            raise ValueError(f"duplicate package artifact hash: {file_hash}")
        seen_hashes.add(file_hash)
        if not bundle_name or Path(bundle_name).name != bundle_name:
            raise ValueError(f"invalid package artifact filename: {bundle_name}")
        path = root / bundle_name
        if not path.is_file():
            raise ValueError(f"package artifact file missing: {bundle_name}")
        expected_size = int(artifact.get("fileSize") or 0)
        if expected_size < 1 or path.stat().st_size != expected_size:
            raise ValueError(f"package artifact size mismatch: {bundle_name}")
        actual_hash = _file_sha256(path)
        if actual_hash != file_hash:
            raise ValueError(
                f"package artifact hash mismatch: expected {file_hash}, got {actual_hash}"
            )
        validated.append(artifact)
    return validated


def _import_artifacts(
    *,
    database_path: str | Path,
    artifacts: list[dict[str, object]],
    files_dir: Path | None,
) -> int:
    if not artifacts:
        return 0
    if files_dir is None:
        raise ValueError("package artifact files directory is required")
    database = Path(database_path)
    downloads_root = database.resolve().parent / "downloads"
    imported: list[tuple[dict[str, object], Path]] = []
    for artifact in artifacts:
        platform = _safe_path_segment(str(artifact.get("platform") or "unknown"))
        bundle_name = str(artifact["bundleName"])
        source = files_dir / bundle_name
        destination = downloads_root / platform / bundle_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_file() or _file_sha256(destination) != artifact["fileHash"]:
            temporary = destination.with_suffix(f"{destination.suffix}.tmp")
            shutil.copy2(source, temporary)
            if _file_sha256(temporary) != artifact["fileHash"]:
                temporary.unlink(missing_ok=True)
                raise ValueError(f"copied artifact hash mismatch: {bundle_name}")
            temporary.replace(destination)
        imported.append((artifact, destination))

    with sqlite3.connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        for artifact, destination in imported:
            file_hash = str(artifact["fileHash"])
            existing = connection.execute(
                "SELECT id FROM resume_artifacts WHERE file_hash = ? "
                "ORDER BY updated_at DESC, id DESC LIMIT 1",
                (file_hash,),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    """
                    UPDATE resume_artifacts SET
                      file_path = ?,
                      platform_conversation_id = CASE
                        WHEN platform_conversation_id = '' THEN ? ELSE platform_conversation_id END,
                      candidate_name_from_platform = CASE
                        WHEN candidate_name_from_platform = '' THEN ?
                        ELSE candidate_name_from_platform END,
                      position = CASE WHEN position = '' THEN ? ELSE position END
                    WHERE file_hash = ?
                    """,
                    (
                        str(destination),
                        str(artifact.get("platformConversationId") or ""),
                        str(artifact.get("candidateName") or ""),
                        str(artifact.get("position") or ""),
                        file_hash,
                    ),
                )
                continue
            conflicting = connection.execute(
                "SELECT file_hash FROM resume_artifacts WHERE id = ?",
                (str(artifact["id"]),),
            ).fetchone()
            if conflicting is not None:
                raise ValueError(f"package artifact id conflict: {artifact['id']}")
            connection.execute(
                """
                INSERT INTO resume_artifacts (
                  id, session_id, platform, owner, platform_conversation_id,
                  candidate_name_from_platform, position, file_path, file_hash,
                  source_kind, parse_status, parsed_name, resume_id, error,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(artifact["id"]),
                    str(artifact.get("sessionId") or ""),
                    str(artifact.get("platform") or ""),
                    str(artifact.get("owner") or ""),
                    str(artifact.get("platformConversationId") or ""),
                    str(artifact.get("candidateName") or ""),
                    str(artifact.get("position") or ""),
                    str(destination),
                    file_hash,
                    str(artifact.get("sourceKind") or ""),
                    str(artifact.get("parseStatus") or "pending"),
                    str(artifact.get("parsedName") or ""),
                    str(artifact.get("resumeId") or ""),
                    str(artifact.get("error") or ""),
                    str(artifact.get("createdAt") or ""),
                    str(artifact.get("updatedAt") or ""),
                ),
            )
        connection.commit()
    return len(imported)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path_segment(value: str) -> str:
    normalized = "".join(
        char for char in value.strip().lower() if char.isalnum() or char in {"-", "_"}
    )
    return normalized or "unknown"


def _load_package(path: Path) -> dict[str, object]:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("package root must be an object")
    return payload


def _date_value(value: object, field_name: str) -> date:
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError as error:
        raise ValueError(f"invalid package {field_name}") from error


def _event_day(event: AutomationContactEvent) -> date:
    try:
        occurred_at = datetime.fromisoformat(event.occurred_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid event occurredAt: {event.id}") from error
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    return occurred_at.astimezone(CHINA_TZ).date()


if __name__ == "__main__":
    raise SystemExit(main())
