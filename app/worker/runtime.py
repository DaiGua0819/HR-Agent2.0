"""单 worker 运行时装配。

Worker 串行处理一个负责人的三平台页面。Phase 7a 默认启用 dry-run，所有真实平台
副作用在 adapter 边界记录意图但不执行。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.agent.graph import build_recruit_graph
from app.agent.persistence import build_persistence_from_settings
from app.agent.runner import ConversationRunner
from app.browser.manager import BrowserManager
from app.core.constants import Platform
from app.domain.conversation.repository import ConversationRepository
from app.domain.resume.artifacts import ResumeArtifactStore
from app.evaluation.decision_log import GLOBAL_DECISION_SINK, InMemoryDecisionSink
from app.platforms.registry import get_platform_adapter
from app.settings import load_settings

DEFAULT_DRAIN_MAX_CONTACTS = 300


@dataclass
class WorkerRuntime:
    """worker 运行期上下文。"""

    owner: str
    port: int
    cdp_port: int = 0
    browser_backend: str = "fake"
    decision_sink: InMemoryDecisionSink = field(default_factory=lambda: GLOBAL_DECISION_SINK)
    browser: BrowserManager | None = None
    agent_ready: bool = False
    agent_busy: bool = False
    paused: set[Platform] = field(default_factory=set)
    events: list[dict[str, object]] = field(default_factory=list)
    conversation_repository: ConversationRepository | None = None
    artifact_store: ResumeArtifactStore | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def start(self) -> None:
        """启动浏览器管理器并准备共享 agent。"""

        if self.browser is None:
            self.browser = BrowserManager(
                owner=self.owner,
                cdp_port=self.cdp_port,
                backend=self.browser_backend,
            )
        await self.browser.start()
        if self.conversation_repository is None or self.artifact_store is None:
            self.conversation_repository, self.artifact_store = build_persistence_from_settings()
        self.agent_ready = True

    async def process_messages(self, platform: Platform) -> dict[str, object]:
        """串行处理某平台未读消息。"""

        async with self._lock:
            self.agent_busy = True
            self.events.append({"event": "start", "platform": platform.value})
            try:
                if platform in self.paused:
                    return {"accepted": False, "paused": True, "platform": platform.value}
                await self.start()
                adapter = self._adapter(platform)
                await self._prepare_message_adapter(adapter)
                ref = await self._find_next_unread_thread(adapter, set())
                if ref is None:
                    return {"accepted": True, "processed": 0, "platform": platform.value}
                state = await self._run_current_conversation(adapter)
                contact = await self._contact_payload(state, fallback_id=ref.conversation_id)
                return {
                    "accepted": True,
                    "processed": 1,
                    "owner": self.owner,
                    "platform": platform.value,
                    **contact,
                    "dryRun": load_settings().dry_run,
                }
            finally:
                self.events.append({"event": "finish", "platform": platform.value})
                self.agent_busy = False

    async def drain_messages(
        self,
        platform: Platform,
        *,
        max_contacts: int = DEFAULT_DRAIN_MAX_CONTACTS,
    ) -> dict[str, object]:
        """Process all currently discoverable unread contacts for one platform."""

        if max_contacts < 1:
            raise ValueError("max_contacts must be at least 1")

        async with self._lock:
            self.agent_busy = True
            self.events.append({"event": "drain_start", "platform": platform.value})
            try:
                if platform in self.paused:
                    return {
                        "accepted": False,
                        "paused": True,
                        "processed": 0,
                        "owner": self.owner,
                        "platform": platform.value,
                        "contacts": [],
                        "drained": False,
                        "stopReason": "paused",
                    }
                await self.start()
                adapter = self._adapter(platform)
                await self._prepare_message_adapter(adapter)
                contacts: list[dict[str, object]] = []
                seen: set[str] = set()
                while len(contacts) < max_contacts:
                    ref = await self._find_next_unread_thread(adapter, seen)
                    if ref is None:
                        return self._drain_payload(
                            platform,
                            contacts,
                            drained=True,
                            stop_reason="drained",
                        )
                    if ref.conversation_id:
                        seen.add(ref.conversation_id)
                    state = await self._run_current_conversation(adapter)
                    contact = await self._contact_payload(
                        state,
                        fallback_id=ref.conversation_id,
                    )
                    conversation_id = str(contact.get("conversationId") or "")
                    if conversation_id:
                        seen.add(conversation_id)
                    contacts.append(contact)
                return self._drain_payload(
                    platform,
                    contacts,
                    drained=False,
                    stop_reason="max_contacts_reached",
                )
            finally:
                self.events.append({"event": "drain_finish", "platform": platform.value})
                self.agent_busy = False

    async def proactive_contact(
        self,
        platform: Platform,
        *,
        target_position: str = "",
        dry_run: bool | None = None,
    ) -> dict[str, object]:
        """串行执行主动联系任务。"""

        async with self._lock:
            self.agent_busy = True
            try:
                await self.start()
                effective_dry_run = load_settings().dry_run if dry_run is None else dry_run
                result = await self._adapter(platform).proactive_greet(
                    target_position or "电气工程师",
                    dry_run=effective_dry_run,
                )
                return {"accepted": True, "owner": self.owner, "platform": platform.value, **result}
            finally:
                self.agent_busy = False

    async def pause(self, platform: Platform) -> dict[str, object]:
        """暂停某平台自动化。"""

        self.paused.add(platform)
        return {"paused": True, "owner": self.owner, "platform": platform.value}

    async def interview_invite(self, payload: dict[str, Any] | None = None) -> dict[str, object]:
        """执行简历库约面试的平台动作。"""

        async with self._lock:
            self.agent_busy = True
            try:
                await self.start()
                data = payload or {}
                platform = Platform(str(data.get("platform") or ""))
                adapter = self._adapter(platform)
                await adapter.open_chat_page()
                result = await adapter.invite_to_interview(data)
                return {
                    "owner": self.owner,
                    "platform": platform.value,
                    **result,
                }
            finally:
                self.agent_busy = False

    async def status_payload(self) -> dict[str, object]:
        """返回 `/status` 响应。"""

        await self.start()
        health = await self.browser.health() if self.browser else None
        return {
            "status": "ready" if self.agent_ready else "not-ready",
            "owner": self.owner,
            "port": self.port,
            "browserReady": bool(health and health.browser_ready),
            "cdpReady": bool(health and health.cdp_ready),
            "agentReady": self.agent_ready,
            "agentBusy": self.agent_busy,
            "browserBackend": health.backend if health else self.browser_backend,
            "pageCount": health.page_count if health else 0,
            "paused": sorted(item.value for item in self.paused),
            "dryRun": load_settings().dry_run,
        }

    def _adapter(self, platform: Platform):
        if self.browser is None:
            raise RuntimeError("worker_runtime_not_started")
        page = self.browser.page_for(self.owner, platform)
        return get_platform_adapter(
            platform,
            page,
            owner=self.owner,
            dry_run=load_settings().dry_run,
        )

    async def _prepare_message_adapter(self, adapter: Any) -> None:
        await adapter.open_chat_page()
        await adapter.select_unread_filter()
        await adapter.select_positions(None)

    async def _find_next_unread_thread(
        self,
        adapter: Any,
        seen: set[str],
    ):
        return await adapter.find_next_unread_thread(exclude_ids=set(seen))

    async def _run_current_conversation(self, adapter: Any) -> dict[str, object]:
        return await ConversationRunner(
            adapter,
            decision_sink=self.decision_sink,
            conversation_repository=self.conversation_repository,
            artifact_store=self.artifact_store,
        ).run_current()

    async def _contact_payload(
        self,
        state: dict[str, object],
        *,
        fallback_id: str = "",
    ) -> dict[str, object]:
        graph_stage = await self._graph_stage(state)
        return {
            "conversationId": state.get("conversation_id") or fallback_id,
            "nextAction": state.get("next_action"),
            "stage": state.get("stage"),
            "graphStage": graph_stage,
            "decision": state.get("decision"),
        }

    def _drain_payload(
        self,
        platform: Platform,
        contacts: list[dict[str, object]],
        *,
        drained: bool,
        stop_reason: str,
    ) -> dict[str, object]:
        return {
            "accepted": True,
            "processed": len(contacts),
            "owner": self.owner,
            "platform": platform.value,
            "contacts": contacts,
            "drained": drained,
            "stopReason": stop_reason,
            "dryRun": load_settings().dry_run,
        }

    async def _graph_stage(self, state: dict[str, object]) -> str:
        graph = build_recruit_graph()
        graph_state = await graph.ainvoke(
            dict(state),
            config={"configurable": {"thread_id": f"{self.owner}-{state.get('conversation_id')}"}},
        )
        return str(graph_state.get("stage") or "")
