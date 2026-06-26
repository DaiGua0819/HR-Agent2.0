"""BOSS recruiter_* function call 兼容入口。"""

from __future__ import annotations

from typing import Any

from app.agent.tools.boss import boss_tool_schemas


def recruiter_tool_schemas() -> list[dict[str, Any]]:
    """返回 BOSS 平台 recruiter_* 工具 schema。"""

    return boss_tool_schemas()
