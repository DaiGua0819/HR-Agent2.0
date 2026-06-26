"""测试默认关闭 dry-run，保留前期假页面行为断言。"""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("DRY_RUN", "false")


@pytest.fixture(scope="session", autouse=True)
def _close_langgraph_checkpointer():
    """关闭 SQLite async checkpointer，避免 aiosqlite 线程挂住 pytest。"""

    yield
    from app.agent.checkpointer import close_checkpointer

    asyncio.run(close_checkpointer())
