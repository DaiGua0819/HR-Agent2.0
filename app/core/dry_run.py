"""全局 dry-run 安全开关。

dry-run 为 True 时，真实副作用只记录意图，不执行页面点击、消息发送、下载或飞书写入。
读取、判断和本地数据库写入照常执行。
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.evaluation.decision_log import record_decision
from app.settings import load_settings


def is_dry_run(value: bool | None = None) -> bool:
    """解析 dry-run：显式参数优先，否则读取全局 settings。"""

    return load_settings().dry_run if value is None else bool(value)


def record_dry_run_intent(action: str, **payload: Any) -> None:
    """记录一次 dry-run 阻断的真实副作用意图。"""

    record_decision(
        {
            "id": str(uuid4()),
            "event": "dry_run_intent",
            "action": action,
            "dryRun": True,
            **payload,
        }
    )
