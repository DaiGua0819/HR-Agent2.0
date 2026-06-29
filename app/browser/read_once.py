"""真实浏览器 dry-run 读路径冒烟。

该模块只编排读取、判断和 dry-run 意图记录；所有平台副作用仍由 adapter 的 dry-run
边界拦截。
"""

from __future__ import annotations

from app.agent.graph import build_recruit_graph
from app.agent.persistence import build_persistence_from_settings
from app.agent.runner import ConversationRunner
from app.browser.manager import BrowserManager
from app.core.constants import Platform
from app.evaluation.decision_log import GLOBAL_DECISION_SINK, InMemoryDecisionSink
from app.platforms.registry import get_platform_adapter


async def dry_run_read_once(
    manager: BrowserManager,
    *,
    owner: str,
    platform: Platform,
    decision_sink: InMemoryDecisionSink | None = None,
) -> dict[str, object]:
    """在 dry-run 下读取一个未读会话并输出判断意图。"""

    await manager.start()
    page = manager.page_for(owner, platform)
    adapter = get_platform_adapter(platform, page, owner=owner, dry_run=True)
    await adapter.open_chat_page()
    await adapter.select_unread_filter()
    await adapter.select_positions(None)
    ref = await adapter.find_next_unread_thread()
    if ref is None:
        return {"owner": owner, "platform": platform.value, "processed": 0, "dryRun": True}

    conversation_repository, artifact_store = build_persistence_from_settings()
    state = await ConversationRunner(
        adapter,
        decision_sink=decision_sink or GLOBAL_DECISION_SINK,
        conversation_repository=conversation_repository,
        artifact_store=artifact_store,
    ).run_current()
    graph_state = await build_recruit_graph().ainvoke(
        dict(state),
        config={"configurable": {"thread_id": f"dry-run-{owner}-{state.get('conversation_id')}"}},
    )
    return {
        "owner": owner,
        "platform": platform.value,
        "processed": 1,
        "conversationId": state.get("conversation_id"),
        "nextAction": state.get("next_action"),
        "stage": state.get("stage"),
        "graphStage": graph_state.get("stage"),
        "decision": state.get("decision"),
        "dryRun": True,
    }
