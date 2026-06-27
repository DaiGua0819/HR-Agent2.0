"""51job job51_* function call 定义与分发。

Schema 对照旧 `agent_web_server.part014.py`。工具层不识别页面 DOM，只把业务
function call 绑定到 51job adapter 能力。
"""

from __future__ import annotations

from typing import Any

from app.platforms.base import PlatformAdapter

JOB51_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "job51_process_unread_all_positions",
        "description": (
            "Recruiter-side 51job workflow: open 51job chat, click 未读 and 全部岗位, "
            "then handle unread contacts through shared boss_chat_rules. A visible "
            "附件简历/在线简历 entry must not be downloaded until the shared business "
            "rules reach a resume-needed branch such as direct resume, accepted AI "
            "basic conditions, or accepted screening."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "maxTotal": {"type": "integer", "description": "optional safety limit"},
                "targetPosition": {"type": "string", "description": "ignored; uses all positions"},
            },
        },
    },
    {
        "name": "job51_process_current_position",
        "description": "Recruiter-side 51job workflow: process the currently opened candidate.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "job51_answer_candidate_questions",
        "description": "Recruiter-side 51job knowledge-base action for current candidate.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "job51_request_resume",
        "description": (
            "51job resume action for the current candidate, called only after the "
            "business flow has decided a resume is needed. Prefer chat 附件简历: click "
            "it, wait for the .annex-resume PDF preview layer, fetch the bottom 下载 "
            "link/blob as real bytes, verify PDF/doc/docx signatures, save under "
            "data/downloads/job51/, and close the preview. If no chat attachment exists, "
            "click the top-right 在线简历 and download its real exported file. Only when "
            "neither source is available should it fall back to in-chat 求简历 plus "
            "confirmation. Visible 在线简历/附件简历 text alone must never be converted "
            "into a fake PDF."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "job51_proactive_contact_recommended_candidates",
        "description": (
            "51job Talent Telescope proactive workflow: enter via #sensor_recommand_menu, "
            "ensure traditional mode, skip 已看 cards, apply shared proactive thresholds, "
            "then click 立即Hi聊 only for qualified candidates."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "targetPosition": {"type": "string"},
                "maxTotal": {"type": "integer"},
                "dryRun": {"type": "boolean"},
            },
        },
    },
]


def job51_tool_schemas() -> list[dict[str, Any]]:
    """返回 51job 平台 job51_* 工具 schema。"""

    return JOB51_TOOL_SCHEMAS


async def dispatch_job51_tool(
    name: str,
    args: dict[str, Any],
    adapter: PlatformAdapter,
) -> dict[str, Any]:
    """把 51job 工具调用绑定到 adapter 方法。"""

    if name == "job51_process_unread_all_positions":
        await adapter.open_chat_page()
        await adapter.select_unread_filter()
        await adapter.select_positions(None)
        ref = await adapter.find_next_unread_thread()
        return {"ok": True, "nextThread": ref.conversation_id if ref else None}
    if name == "job51_process_current_position":
        conversation = await adapter.read_chat_context()
        return {"ok": True, "conversationId": conversation.id}
    if name == "job51_answer_candidate_questions":
        conversation = await adapter.read_chat_context()
        return {"ok": True, "conversationId": conversation.id}
    if name == "job51_request_resume":
        return await adapter.request_resume()
    if name == "job51_proactive_contact_recommended_candidates":
        return await adapter.proactive_greet(
            str(args.get("targetPosition") or "膨润土销售人员"),
            dry_run=bool(args.get("dryRun")),
        )
    raise KeyError(f"未知 51job 工具: {name}")
