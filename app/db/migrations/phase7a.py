"""Phase 7a 幂等迁移。"""

from __future__ import annotations

from pathlib import Path

from app.db.engine import run_migrations


def migrate(database_path: str | Path | None = None) -> None:
    """执行 Phase 7a schema 迁移。"""

    run_migrations(database_path)
