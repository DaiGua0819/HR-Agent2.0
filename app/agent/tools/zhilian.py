"""智联 zhilian_* function call 定义。"""

from __future__ import annotations

from typing import Any

from app.platforms.base import PlatformAdapter

ZHILIAN_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "zhilian_process_unread_all_positions",
        "description": (
            "Recruiter-side 智联 workflow: process unread messages from 智联聊天. "
            "The backend uses CDP 9226, opens 智联聊天, selects 未读 and 全部职位, "
            "then handles contacts with shared boss_chat_rules screening/knowledge rules."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "maxTotal": {"type": "integer", "description": "optional safety limit, default 40"},
                "targetPosition": {
                    "type": "string",
                    "description": (
                        "optional 智联 position filter; omit for all configured "
                        "智联 positions"
                    ),
                },
            },
        },
    },
    {
        "name": "zhilian_process_current_position",
        "description": "Recruiter-side 智联 workflow: process the currently opened 智联 candidate.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "zhilian_answer_candidate_questions",
        "description": (
            "Recruiter-side 智联 knowledge-base action: answer latest "
            "unanswered questions."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "zhilian_request_resume",
        "description": (
            "Recruiter-side 智联 chat task: request attachment resume by "
            "clicking 要附件简历."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "zhilian_proactive_contact_recommended_candidates",
        "description": (
            "Recruiter-side 智联 proactive workflow for 推荐人才. Opens "
            ".new-shortcut-resume__modal detail first and only clicks "
            "detail-modal 打招呼; never clicks 打电话."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "targetPosition": {
                    "type": "string",
                    "description": "target 智联 recommend position, default 电气工程师",
                },
                "maxTotal": {"type": "integer", "description": "optional safety limit, default 10"},
                "dryRun": {
                    "type": "boolean",
                    "description": "true to preview matched candidates without clicking 打招呼",
                },
            },
        },
    },
]


def zhilian_tool_schemas() -> list[dict[str, Any]]:
    """返回智联平台 zhilian_* 工具 schema。"""

    return ZHILIAN_TOOL_SCHEMAS


async def dispatch_zhilian_tool(
    name: str,
    args: dict[str, Any],
    adapter: PlatformAdapter,
) -> dict[str, Any]:
    """把智联工具调用绑定到 adapter 方法。"""

    if name == "zhilian_process_unread_all_positions":
        await adapter.open_chat_page()
        await adapter.select_unread_filter()
        await adapter.select_positions(args.get("targetPosition"))
        ref = await adapter.find_next_unread_thread()
        return {"ok": True, "nextThread": ref.conversation_id if ref else None}
    if name == "zhilian_process_current_position":
        conversation = await adapter.read_chat_context()
        return {"ok": True, "conversationId": conversation.id}
    if name == "zhilian_answer_candidate_questions":
        conversation = await adapter.read_chat_context()
        return {"ok": True, "conversationId": conversation.id}
    if name == "zhilian_request_resume":
        return await adapter.request_resume()
    if name == "zhilian_proactive_contact_recommended_candidates":
        return await adapter.proactive_greet(
            str(args.get("targetPosition") or "电气工程师"),
            dry_run=bool(args.get("dryRun")),
        )
    raise KeyError(f"未知智联工具: {name}")
