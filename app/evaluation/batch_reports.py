"""批次报告持久化。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.db.engine import connect, run_migrations
from app.evaluation.decision_log import now_iso
from app.settings import load_settings


def save_batch_report(report: dict[str, object], database_path: str | Path | None = None) -> None:
    """保存批次处理报告到 SQLite。"""

    path = Path(database_path) if database_path else load_settings().resolved_database_path
    run_migrations(path)
    payload: dict[str, Any] = dict(report)
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO batch_reports (id, report_type, payload, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                str(payload.get("id") or uuid4()),
                str(payload.get("type") or payload.get("reportType") or "batch"),
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                now_iso(),
            ),
        )
        connection.commit()
