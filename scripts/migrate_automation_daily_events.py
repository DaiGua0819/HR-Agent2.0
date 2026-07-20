"""Export and idempotently import daily recruitment monitoring events."""

from __future__ import annotations

import argparse
import hashlib
import json
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

PACKAGE_VERSION = 1
PACKAGE_TIMEZONE = "Asia/Shanghai"


def build_export_package(
    exported: DailyProjectionExport,
    *,
    start_date: date,
    end_date: date,
    generated_at: str | None = None,
) -> dict[str, object]:
    return {
        "version": PACKAGE_VERSION,
        "timezone": PACKAGE_TIMEZONE,
        "generatedAt": generated_at or datetime.now(UTC).isoformat(),
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "coverage": dict(exported.coverage),
        "summary": dict(exported.summary),
        "events": [
            event.model_dump(by_alias=True, mode="json") for event in exported.events
        ],
    }


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
    apply: bool = False,
) -> dict[str, object]:
    events = validate_package(package)
    applied = 0
    if apply:
        applied = AutomationMonitoringRepository(database_path).upsert_events(events)
    return {"validated": len(events), "applied": applied, "dryRun": not apply}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="export daily events")
    export_parser.add_argument("--database", type=Path, required=True)
    export_parser.add_argument("--runs", type=Path, required=True)
    export_parser.add_argument("--end-date", type=date.fromisoformat)
    export_parser.add_argument("--days", type=int, default=7)
    export_parser.add_argument("--output", type=Path)

    import_parser = subparsers.add_parser("import", help="validate or import a package")
    import_parser.add_argument("--database", type=Path, required=True)
    import_parser.add_argument("--input", type=Path, required=True)
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
        package = build_export_package(
            exported,
            start_date=start_date,
            end_date=end_date,
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
