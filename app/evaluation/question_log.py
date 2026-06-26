"""候选人问题记录持久化。"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from app.db.engine import connect, run_migrations
from app.evaluation.decision_log import now_iso
from app.settings import load_settings


def record_candidate_question(
    question: str,
    *,
    payload: dict[str, object] | None = None,
    database_path: str | Path | None = None,
) -> None:
    """记录候选人提出的问题。"""

    path = Path(database_path) if database_path else load_settings().resolved_database_path
    run_migrations(path)
    data = {"question": question, **(payload or {})}
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO question_logs (id, question, payload, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                question,
                json.dumps(data, ensure_ascii=False, sort_keys=True),
                now_iso(),
            ),
        )
        connection.commit()
