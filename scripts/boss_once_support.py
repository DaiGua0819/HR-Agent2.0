"""BOSS 单次处理脚本的输出辅助函数。"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any


def print_summary(items: list[dict[str, Any]], *, live: bool) -> None:
    """打印 BOSS 单次处理的人类可读小结。"""

    mode_name = "LIVE" if live else "dry-run"
    print(f"\n===== BOSS {mode_name} 小结 =====")
    print(f"处理会话数: {len(items)}")
    if not items:
        print("没有处理到候选人会话。可能没有未读，或会话列表选择器未返回候选人行。")
        return
    for index, item in enumerate(items, start=1):
        candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
        decision = item.get("decision") if isinstance(item.get("decision"), dict) else {}
        print(f"\n[{index}] 会话: {item.get('conversationId')}")
        print(f"候选人: {candidate.get('name') or ''}")
        print(f"识别岗位: {item.get('job') or candidate.get('applied_position') or '未识别'}")
        print(f"规则来源: {item.get('ruleSource') or '未命中'}")
        print(
            "最后消息: "
            f"{json.dumps(jsonable(item.get('lastMessage') or {}), ensure_ascii=False)}"
        )
        print(f"打算动作: {item.get('action') or '无'}")
        print(f"原因/阶段: {item.get('stage') or ''}")
        sent_messages = item.get("sentMessages")
        if isinstance(sent_messages, list) and sent_messages:
            print(f"拟发送/已发送文本: {json.dumps(jsonable(sent_messages), ensure_ascii=False)}")
        screening = decision.get("screening") if isinstance(decision.get("screening"), dict) else {}
        if screening:
            print(
                "筛选状态: "
                f"{screening.get('status') or ''} / {screening.get('reason') or ''}"
            )
        reliable_actions = item.get("reliableActions")
        if isinstance(reliable_actions, list) and reliable_actions:
            print(f"可靠动作: {json.dumps(jsonable(reliable_actions), ensure_ascii=False)}")
        print(f"决策详情: {json.dumps(jsonable(decision), ensure_ascii=False)}")


def reliable_actions_since(page: Any, start: int) -> list[dict[str, Any]]:
    """返回本轮候选人处理新增的可靠动作记录。"""

    actions = getattr(page, "reliable_actions", [])
    if not isinstance(actions, list):
        return []
    return [dict(item) for item in actions[start:] if isinstance(item, dict)]


def jsonable(value: Any) -> Any:
    """把 dataclass 等对象规整成可 JSON 打印的值。"""

    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        if hasattr(value, "__dataclass_fields__"):
            return asdict(value)
        return str(value)
