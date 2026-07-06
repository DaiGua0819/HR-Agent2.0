from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.core.constants import Platform
from app.platforms.types import ConversationRef
from app.worker.runtime import WorkerRuntime


def test_worker_drain_messages_processes_every_unread_contact(monkeypatch) -> None:
    adapter = DrainAdapter(["conv-1", "conv-2"])
    runtime = WorkerRuntime(owner="owner-a", port=8801)

    _install_runtime_fakes(monkeypatch, runtime, adapter)

    payload = asyncio.run(runtime.drain_messages(Platform.BOSS, max_contacts=5))

    assert payload["accepted"] is True
    assert payload["processed"] == 2
    assert payload["drained"] is True
    assert payload["stopReason"] == "drained"
    assert [item["conversationId"] for item in payload["contacts"]] == ["conv-1", "conv-2"]
    assert adapter.events[:3] == ["open_chat_page", "select_unread_filter", "select_positions"]
    assert adapter.find_excludes == [set(), {"conv-1"}, {"conv-1", "conv-2"}]


def test_worker_drain_messages_stops_at_max_contacts(monkeypatch) -> None:
    adapter = DrainAdapter(["conv-1", "conv-2", "conv-3"])
    runtime = WorkerRuntime(owner="owner-a", port=8801)

    _install_runtime_fakes(monkeypatch, runtime, adapter)

    payload = asyncio.run(runtime.drain_messages(Platform.BOSS, max_contacts=2))

    assert payload["processed"] == 2
    assert payload["drained"] is False
    assert payload["stopReason"] == "max_contacts_reached"
    assert [item["conversationId"] for item in payload["contacts"]] == ["conv-1", "conv-2"]
    assert adapter.find_excludes == [set(), {"conv-1"}]


def _install_runtime_fakes(
    monkeypatch,
    runtime: WorkerRuntime,
    adapter: DrainAdapter,
) -> None:
    async def fake_start() -> None:
        runtime.agent_ready = True

    async def fake_graph_stage(state: dict[str, object]) -> str:
        return f"graph-{state.get('conversation_id')}"

    runtime.start = fake_start  # type: ignore[method-assign]
    runtime._adapter = lambda platform: adapter  # type: ignore[method-assign]
    runtime._graph_stage = fake_graph_stage  # type: ignore[method-assign]
    monkeypatch.setattr("app.worker.runtime.ConversationRunner", FakeRunner)
    monkeypatch.setattr(
        "app.worker.runtime.load_settings",
        lambda: SimpleNamespace(dry_run=False),
    )


class FakeRunner:
    def __init__(self, adapter: DrainAdapter, **kwargs: object) -> None:
        _ = kwargs
        self.adapter = adapter

    async def run_current(self) -> dict[str, object]:
        conversation_id = self.adapter.current_conversation_id
        return {
            "conversation_id": conversation_id,
            "next_action": f"next-{conversation_id}",
            "stage": f"stage-{conversation_id}",
            "decision": {"action": "wait"},
        }


class DrainAdapter:
    def __init__(self, conversation_ids: list[str]) -> None:
        self.conversation_ids = conversation_ids
        self.current_conversation_id = ""
        self.events: list[str] = []
        self.find_excludes: list[set[str]] = []

    async def open_chat_page(self) -> None:
        self.events.append("open_chat_page")

    async def select_unread_filter(self) -> dict[str, object]:
        self.events.append("select_unread_filter")
        return {"selected": True}

    async def select_positions(self, target_position: str | None = None) -> dict[str, object]:
        _ = target_position
        self.events.append("select_positions")
        return {"selected": True}

    async def find_next_unread_thread(
        self,
        *,
        exclude_ids: set[str] | None = None,
    ) -> ConversationRef | None:
        excluded = set(exclude_ids or set())
        self.find_excludes.append(excluded)
        for conversation_id in self.conversation_ids:
            if conversation_id not in excluded:
                self.current_conversation_id = conversation_id
                return ConversationRef(Platform.BOSS, "owner-a", conversation_id)
        return None
