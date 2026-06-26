"""BOSS recruiter_* function call 定义与分发。

Schema 对照旧 `agent_web_server.part014.py` 中 `recruiter_*` 定义；动作只调用
平台 adapter，不在工具层猜 DOM。
"""

from __future__ import annotations

from typing import Any

from app.platforms.base import PlatformAdapter

BOSS_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "recruiter_process_unread_all_positions",
        "description": (
            "Recruiter-side BOSS workflow: process all unread recruitment messages "
            "across configured positions. Direct-resume roles send configured "
            "resumeRequestPrompt before 求简历 when the platform policy requires it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "maxTotal": {"type": "integer", "description": "optional safety limit"},
                "dateScope": {"type": "string", "description": "today/yesterday/today_yesterday"},
                "targetPosition": {"type": "string", "description": "optional position filter"},
            },
        },
    },
    {
        "name": "recruiter_process_current_position",
        "description": "Recruiter-side BOSS workflow: process the currently opened candidate.",
        "parameters": {
            "type": "object",
            "properties": {
                "targetCandidate": {"type": "string"},
                "openUnreplied": {"type": "boolean"},
            },
        },
    },
    {
        "name": "recruiter_answer_candidate_questions",
        "description": "Answer latest BOSS candidate questions from companyKnowledgeBase.",
        "parameters": {"type": "object", "properties": {"targetCandidate": {"type": "string"}}},
    },
    {
        "name": "recruiter_send_company_info",
        "description": "Send BOSS AI application-development company/basic-condition phrase.",
        "parameters": {"type": "object", "properties": {"targetCandidate": {"type": "string"}}},
    },
    {
        "name": "recruiter_send_common_phrase",
        "description": "Send a configured BOSS common phrase for AI application-development roles.",
        "parameters": {
            "type": "object",
            "properties": {
                "phraseKey": {"type": "string"},
                "phrase": {"type": "string"},
                "targetCandidate": {"type": "string"},
            },
        },
    },
    {
        "name": "recruiter_request_resume",
        "description": "Use BOSS 求简历 toolbar button and complete the request flow.",
        "parameters": {
            "type": "object",
            "properties": {
                "openUnreplied": {"type": "boolean"},
                "targetCandidate": {"type": "string"},
            },
        },
    },
    {
        "name": "recruiter_screen_basic_conditions",
        "description": "Legacy BOSS AI basic-condition flow for current/opened candidate.",
        "parameters": {
            "type": "object",
            "properties": {
                "openUnreplied": {"type": "boolean"},
                "targetCandidate": {"type": "string"},
            },
        },
    },
    {
        "name": "recruiter_screen_recent_with_followup",
        "description": "Process recent BOSS contacts and monitor follow-up replies.",
        "parameters": {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
                "idleSeconds": {"type": "integer"},
            },
        },
    },
    {
        "name": "recruiter_proactive_contact_recommended_candidates",
        "description": (
            "BOSS 推荐牛人 proactive workflow: confirm .job-selecter-wrap "
            ".ui-dropmenu-label, inspect .candidate-card-wrap, open .dialog-wrap.active, "
            "apply proactive thresholds, then click button.btn-greet only."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "targetPosition": {"type": "string"},
                "maxTotal": {"type": "integer"},
                "dryRun": {"type": "boolean"},
                "requireMatch": {"type": "boolean"},
            },
        },
    },
    {
        "name": "recruiter_mark_unsuitable",
        "description": "Mark current or named BOSS candidate as 不合适 after confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "targetCandidate": {"type": "string"},
                "openUnreplied": {"type": "boolean"},
            },
        },
    },
]


def boss_tool_schemas() -> list[dict[str, Any]]:
    """返回 BOSS 平台 recruiter_* 工具 schema。"""

    return BOSS_TOOL_SCHEMAS


async def dispatch_boss_tool(
    name: str,
    args: dict[str, Any],
    adapter: PlatformAdapter,
) -> dict[str, Any]:
    """把 BOSS 工具调用绑定到 adapter 方法。"""

    if name == "recruiter_process_unread_all_positions":
        await adapter.open_chat_page()
        await adapter.select_unread_filter()
        await adapter.select_positions(args.get("targetPosition"))
        ref = await adapter.find_next_unread_thread()
        return {"ok": True, "nextThread": ref.conversation_id if ref else None}
    if name == "recruiter_process_current_position":
        if args.get("openUnreplied"):
            await adapter.find_next_unread_thread()
        conversation = await adapter.read_chat_context()
        return {"ok": True, "conversationId": conversation.id}
    if name == "recruiter_answer_candidate_questions":
        conversation = await adapter.read_chat_context()
        return {"ok": True, "conversationId": conversation.id}
    if name == "recruiter_send_company_info":
        result = await adapter.send_company_info()
        return {"ok": result.sent, "message": result.message}
    if name == "recruiter_send_common_phrase":
        result = await adapter.send_common_phrase(
            phrase_key=str(args.get("phraseKey") or ""),
            phrase=str(args.get("phrase") or ""),
        )
        return {"ok": result.sent, "message": result.message}
    if name == "recruiter_request_resume":
        if args.get("openUnreplied"):
            await adapter.find_next_unread_thread()
        return await adapter.request_resume()
    if name == "recruiter_screen_basic_conditions":
        if args.get("openUnreplied"):
            await adapter.find_next_unread_thread()
        result = await adapter.send_company_info()
        return {"ok": result.sent, "message": result.message}
    if name == "recruiter_screen_recent_with_followup":
        return {"ok": True, "watched": int(args.get("count") or 10), "phase": "memory_only"}
    if name == "recruiter_proactive_contact_recommended_candidates":
        return await adapter.proactive_greet(
            str(args.get("targetPosition") or "应用技术经理（工业涂料领域）"),
            dry_run=bool(args.get("dryRun")),
        )
    if name == "recruiter_mark_unsuitable":
        return await adapter.mark_unsuitable(reason=str(args.get("targetCandidate") or ""))
    raise KeyError(f"未知 BOSS 工具: {name}")
