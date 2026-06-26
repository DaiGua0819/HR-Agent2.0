"""function call schema 注册表。"""

from __future__ import annotations

from typing import Any

from app.agent.tools.boss import boss_tool_schemas, dispatch_boss_tool
from app.agent.tools.job51 import dispatch_job51_tool, job51_tool_schemas
from app.agent.tools.zhilian import dispatch_zhilian_tool, zhilian_tool_schemas
from app.platforms.base import PlatformAdapter


def list_tool_schemas() -> list[dict[str, Any]]:
    """返回 LLM 可见的工具 schema。"""

    return [*zhilian_tool_schemas(), *boss_tool_schemas(), *job51_tool_schemas()]


async def dispatch_tool(
    name: str,
    args: dict[str, Any],
    *,
    adapter: PlatformAdapter,
) -> dict[str, Any]:
    """按工具名分发到对应平台 adapter。"""

    if name.startswith("zhilian_"):
        return await dispatch_zhilian_tool(name, args, adapter)
    if name.startswith("recruiter_"):
        return await dispatch_boss_tool(name, args, adapter)
    if name.startswith("job51_"):
        return await dispatch_job51_tool(name, args, adapter)
    raise KeyError(f"未注册工具: {name}")
