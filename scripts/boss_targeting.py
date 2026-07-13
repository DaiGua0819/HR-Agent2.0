"""BOSS 指定会话补处理 helper。

真实页面 dry-run 读取会把未读会话标为已读；这些函数只用于按已知会话 id
补处理目标会话，避免再次盲扫全部列表。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.agent.runner import ConversationRunner
from app.platforms.boss import selectors
from app.platforms.boss.adapter import BossAdapter
from app.platforms.boss.interaction import boss_click_element


async def select_all_filter(page: Any) -> dict[str, object]:
    """切到 BOSS 全部会话，供指定 id 补处理使用。"""

    result: dict[str, object] = {"selected": False, "reason": "all_filter_not_found"}
    candidates = await page.query_all(selectors.MESSAGE_FILTER_OPTION)
    if not candidates:
        candidates = await page.query_all(selectors.UNREAD_FILTER)
    for element in candidates:
        label = (await element.text()).strip()
        if "".join(label.split()) == "全部":
            click = await boss_click_element(
                page,
                element,
                label="BOSS全部会话筛选",
                verify=lambda: _verify_message_filter(page, "全部"),
            )
            result = {"selected": bool(click.get("ok")), "label": label, "click": click}
            break
    await asyncio.sleep(1)
    return result


async def process_boss_targets(
    adapter: BossAdapter,
    conversation_ids: list[str],
    *,
    conversation_repository: Any | None = None,
    artifact_store: Any | None = None,
) -> list[dict[str, Any]]:
    """按会话 id 逐个处理 BOSS 会话。"""

    summaries: list[dict[str, Any]] = []
    for conversation_id in conversation_ids:
        clicked = await _click_conversation_by_id(adapter.page, conversation_id)
        if not clicked:
            summaries.append(_not_found_summary(conversation_id))
            continue
        context = await _wait_for_context(adapter)
        state = await ConversationRunner(
            adapter,
            conversation_repository=conversation_repository,
            artifact_store=artifact_store,
        ).run_current()
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
    deadline = asyncio.get_running_loop().time() + 6
    while asyncio.get_running_loop().time() < deadline:
        for row in await page.query_all(selectors.SESSION_ITEM):
            row_ids = {
                str(await row.attr(name) or "").lstrip("_")
                for name in ("id", "data-id", "data-uid")
            }
            id_matches = bool(raw_norm and raw_norm in row_ids)
            label_matches = False
            if not id_matches and not raw_norm.replace("-", "").isdigit():
                label_matches = (await row.text()).strip() == raw
            if not id_matches and not label_matches:
                continue
            click = await boss_click_element(
                page,
                row,
                label=f"BOSS指定会话 {raw}",
                verify=lambda: _verify_chat_ready(page),
            )
            if not click.get("ok"):
                return False
            await asyncio.sleep(1)
            return True
        await asyncio.sleep(0.25)
    return False


async def _verify_chat_ready(page: Any) -> dict[str, object]:
    ready = await page.wait_for(selectors.CHAT_INPUT, timeout_ms=6500)
    return {"verified": bool(ready), "reason": "" if ready else "chat_input_not_ready"}


async def _verify_message_filter(page: Any, expected: str) -> dict[str, object]:
    try:
        actual = await page.eval_js(
            """
            () => {
              const active = document.querySelector(".chat-message-filter-left span.active");
              return active && active.innerText ? active.innerText.trim() : "";
            }
            """
        )
    except Exception:
        actual = ""
    actual = str(actual or "")
    return {
        "verified": actual == expected,
        "actual": actual,
        "expected": expected,
        "reason": "" if actual == expected else "message_filter_not_active",
    }


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
