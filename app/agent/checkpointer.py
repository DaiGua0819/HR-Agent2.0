"""LangGraph 状态持久化。

Phase 7a 使用官方 `langgraph-checkpoint-sqlite` 的 `AsyncSqliteSaver`。由于图构建是同步的、
而 AsyncSqliteSaver 必须在运行中的 event loop 内构造，本模块提供一个 lazy wrapper，
在第一次异步读写 checkpoint 时创建真正 saver。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.db.engine import run_migrations
from app.settings import load_settings

_CHECKPOINTER: LazyAsyncSqliteCheckpointer | None = None


class LazyAsyncSqliteCheckpointer(BaseCheckpointSaver):
    """按 event loop 懒加载 AsyncSqliteSaver。"""

    config_specs: list[Any] = []

    def __init__(self, database_path: str | Path) -> None:
        super().__init__()
        self.database_path = Path(database_path)
        self._savers: dict[int, AsyncSqliteSaver] = {}
        self._version_helper = MemorySaver()

    async def _saver(self) -> AsyncSqliteSaver:
        loop_id = id(asyncio.get_running_loop())
        saver = self._savers.get(loop_id)
        if saver is None:
            connection = await aiosqlite.connect(str(self.database_path))
            saver = AsyncSqliteSaver(connection)
            await saver.setup()
            self._savers[loop_id] = saver
        return saver

    def get_next_version(self, current: str | None, channel: None) -> str:
        """复用官方 memory saver 的版本号生成逻辑。"""

        return self._version_helper.get_next_version(current, channel)

    async def aget_tuple(self, config: dict[str, Any]) -> Any:
        """异步读取 checkpoint tuple。"""

        return await (await self._saver()).aget_tuple(config)

    async def aget(self, config: dict[str, Any]) -> Any:
        """异步读取 checkpoint。"""

        return await (await self._saver()).aget(config)

    async def aput(
        self,
        config: dict[str, Any],
        checkpoint: Any,
        metadata: Any,
        new_versions: Any,
    ) -> dict[str, Any]:
        """异步保存 checkpoint。"""

        return await (await self._saver()).aput(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: dict[str, Any],
        writes: Any,
        task_id: str,
        task_path: str = "",
    ) -> None:
        """异步保存中间 writes。"""

        return await (await self._saver()).aput_writes(config, writes, task_id, task_path)

    async def alist(
        self,
        config: dict[str, Any] | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[Any]:
        """异步列出 checkpoint。"""

        async for item in (await self._saver()).alist(
            config,
            filter=filter,
            before=before,
            limit=limit,
        ):
            yield item


def get_checkpointer() -> LazyAsyncSqliteCheckpointer:
    """返回 SQLite async checkpointer。"""

    global _CHECKPOINTER
    if _CHECKPOINTER is None:
        path = load_settings().resolved_database_path
        run_migrations(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        _CHECKPOINTER = LazyAsyncSqliteCheckpointer(path)
    return _CHECKPOINTER


async def aload_checkpoint(conversation_id: str) -> dict[str, Any] | None:
    """按 thread_id 异步读取最新 checkpoint，供排查使用。"""

    item = await get_checkpointer().aget({"configurable": {"thread_id": conversation_id}})
    return dict(item) if item else None


async def close_checkpointer() -> None:
    """关闭测试或进程退出时遗留的 aiosqlite 连接。"""

    global _CHECKPOINTER
    if _CHECKPOINTER is None:
        return
    for saver in list(_CHECKPOINTER._savers.values()):
        await saver.conn.close()
    _CHECKPOINTER._savers.clear()
    _CHECKPOINTER = None


def load_checkpoint(conversation_id: str) -> dict[str, Any] | None:
    """同步读取接口保留占位；异步图状态请使用 `aload_checkpoint`。"""

    _ = conversation_id
    return None
