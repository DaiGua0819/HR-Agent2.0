"""BOSS 指定会话补处理 helper。

真实页面 dry-run 读取会把未读会话标为已读；这些函数只用于按已知会话 id
补处理目标会话，避免再次盲扫全部列表。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agent.runner import ConversationRunner
from app.browser.reliable_actions import reliable_click_element
from app.platforms.boss import selectors
from app.platforms.boss.adapter import BossAdapter


async def select_all_filter(page: Any) -> dict[str, object]:
    """切到 BOSS 全部会话，供指定 id 补处理使用。"""

    result: dict[str, object] = {"selected": False, "reason": "all_filter_not_found"}
    for element in await page.query_all(selectors.UNREAD_FILTER):
        label = (await element.text()).strip()
        if label == "全部" or (label.startswith("全部") and len(label) <= 12):
            click = await reliable_click_element(page, element, label="BOSS全部会话筛选")
            result = {"selected": bool(click.get("ok")), "label": label, "click": click}
            break
    await asyncio.sleep(1)
    return result


async def process_boss_targets(
    adapter: BossAdapter, conversation_ids: list[str]
) -> list[dict[str, Any]]:
    """按会话 id 逐个处理 BOSS 会话。"""

    summaries: list[dict[str, Any]] = []
    for conversation_id in conversation_ids:
        clicked = await _click_conversation_by_id(adapter.page, conversation_id)
        if not clicked:
            summaries.append(_not_found_summary(conversation_id))
            continue
        context = await _wait_for_context(adapter)
        state = await ConversationRunner(adapter).run_current()
        messages = state.get("messages") if isinstance(state.get("messages"), list) else []
        candidate = state.get("candidate") if isinstance(state.get("candidate"), dict) else {}
        summaries.append(
            {
                "conversationId": str(state.get("conversation_id") or conversation_id),
                "candidate": candidate or {"name": context.candidate.name},
                "job": state.get("applied_position") or context.candidate.applied_position,
                "lastMessage": messages[-1] if messages else _last_message_from_context(context),
                "action": state.get("next_action") or "",
                "stage": state.get("stage") or "",
                "ruleSource": state.get("rule_source") or "",
                "sentMessages": state.get("sent_messages") or [],
                "decision": state.get("decision") or {},
            }
        )
    return summaries


async def _click_conversation_by_id(page: Any, conversation_id: str) -> bool:
    raw = conversation_id.strip()
    raw_norm = raw.lstrip("_")
    for row in await page.query_all(selectors.SESSION_ITEM):
        row_id = str(await row.attr("id") or "")
        label = (await row.text()).strip()
        if row_id.lstrip("_") != raw_norm and label != raw:
            continue
        click = await reliable_click_element(
            page,
            row,
            label=f"BOSS指定会话 {raw}",
            verify=lambda: _verify_chat_ready(page),
        )
        clicked = bool(click.get("ok"))
        if not clicked:
            return False
        await asyncio.sleep(1)
        return True
    return False


async def _verify_chat_ready(page: Any) -> dict[str, object]:
    ready = await page.wait_for(selectors.CHAT_INPUT, timeout_ms=6500)
    return {"verified": bool(ready), "reason": "" if ready else "chat_input_not_ready"}


async def _wait_for_context(adapter: BossAdapter, *, timeout_seconds: float = 6) -> Any:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    latest = await adapter.read_chat_context()
    while not latest.messages and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.4)
        latest = await adapter.read_chat_context()
    return latest


def _last_message_from_context(context: Any) -> dict[str, str]:
    if not getattr(context, "messages", None):
        return {}
    message = context.messages[-1]
    return {
        "sender": str(message.sender),
        "text": message.text,
        "raw_text": message.raw_text,
    }


def _not_found_summary(conversation_id: str) -> dict[str, Any]:
    return {
        "conversationId": conversation_id,
        "action": "skip",
        "stage": "target_not_found",
        "decision": {"reason": "target_not_found"},
    }
