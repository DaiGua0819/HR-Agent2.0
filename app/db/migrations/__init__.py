"""SQLite 幂等迁移入口。"""

from __future__ import annotations

from pathlib import Path

from app.db.engine import run_migrations


def migrate(database_path: str | Path | None = None) -> None:
    """对目标 SQLite 执行幂等迁移。"""

    run_migrations(database_path)
