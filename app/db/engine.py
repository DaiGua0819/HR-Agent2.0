"""SQLite 连接、初始化与幂等迁移。

所有数据库路径都来自 settings 或调用方传入；验证线上库副本时，把 `DATABASE_PATH`
指向副本即可。迁移只执行幂等 DDL，不删除、不覆盖已有数据。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.settings import load_settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _as_path(database_path: str | Path | None) -> Path:
    if database_path is not None:
        return Path(database_path)
    return load_settings().resolved_database_path


def connect(
    database_path: str | Path | None = None,
    *,
    read_only: bool = False,
) -> sqlite3.Connection:
    """连接 SQLite；read_only=True 用于旧库或线上副本只读巡检。"""

    path = _as_path(database_path)
    if read_only:
        uri = path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def load_schema() -> str:
    """读取当前版本建表语句。"""

    return SCHEMA_PATH.read_text(encoding="utf-8")


def initialize_database(database_path: str | Path | None = None) -> None:
    """按 schema.sql 初始化新库。"""

    with connect(database_path) as connection:
        connection.executescript(load_schema())


def run_migrations(database_path: str | Path | None = None) -> None:
    """执行幂等迁移。"""

    initialize_database(database_path)
    with connect(database_path) as connection:
        _add_column_if_missing(connection, "batch_items", "file_path", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(connection, "batch_items", "message", "TEXT")
        _add_column_if_missing(connection, "batch_items", "resume_id", "TEXT")
        connection.commit()


def _add_column_if_missing(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
