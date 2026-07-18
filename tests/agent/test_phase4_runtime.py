"""Phase 4：控制面 + worker 运行时装配测试。

测试使用进程内 worker client 和 FakePage，不启动真实浏览器、不连接 DB。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.accounts.manager import AccountManager
from app.control_plane.dispatcher import Dispatcher
from app.control_plane.main import create_app
from app.control_plane.worker_client import InProcessWorkerClient, WorkerClient
from app.core.constants import Platform
from app.platforms.job51.adapter import Job51Adapter
from app.platforms.types import ConversationRef
from app.worker.runtime import WorkerRuntime
from fastapi.testclient import TestClient


def test_control_plane_process_all_dispatches_in_configured_serial_order() -> None:
    """控制面 process-all 按 boss→51→智联，每平台和新红在前串行派发。"""

    dispatcher = Dispatcher(clients=_runtime_clients())
    app = create_app(dispatcher=dispatcher)
    with TestClient(app) as client:
        response = client.post("/automation/process-all")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "serial"
    assert payload["order"] == [
        "和新红:boss",
        "宋峰峰:boss",
        "和新红:job51",
        "宋峰峰:job51",
        "和新红:zhilian",
        "宋峰峰:zhilian",
    ]
    assert [item["owner"] for item in payload["results"]] == ["和新红", "宋峰峰"] * 3


def test_dispatcher_is_serial_not_parallel() -> None:
    """Dispatcher 串行 await 每个 worker 调用，不并发抢同一浏览器。"""

    tracker = SerialTracker()
    dispatcher = Dispatcher(
        account_manager=AccountManager(),
        clients={
            "和新红": TrackingWorkerClient("和新红", tracker),
            "宋峰峰": TrackingWorkerClient("宋峰峰", tracker),
        },
    )
    payload = asyncio.run(dispatcher.process_all())
    assert tracker.max_active == 1
    assert payload["order"] == [
        "和新红:boss",
        "宋峰峰:boss",
        "和新红:job51",
        "宋峰峰:job51",
        "和新红:zhilian",
        "宋峰峰:zhilian",
    ]


def test_worker_status_ready_with_fake_pages() -> None:
    """worker runtime 在 FakePage 装配下返回 ready。"""

    runtime = WorkerRuntime(owner="和新红", port=8801, cdp_port=9222)
    status = asyncio.run(runtime.status_payload())
    assert status["status"] == "ready"
    assert status["browserReady"] is True
    assert status["cdpReady"] is True
    assert status["agentReady"] is True
    assert status["pageCount"] == 3


def test_worker_drain_counts_unique_contact_payloads() -> None:
    """Dry-run can leave unread rows visible; stale duplicate reads must not count twice."""

    runtime = DuplicateContactRuntime()

    payload = asyncio.run(runtime.drain_messages(Platform.JOB51, max_contacts=2))

    assert payload["processed"] == 2
    assert [item["conversationId"] for item in payload["contacts"]] == [
        "candidate-a",
        "candidate-b",
    ]


def test_worker_client_uses_long_timeout_for_browser_automation() -> None:
    """Browser automation may legitimately take several minutes per contact."""

    client = WorkerClient("http://127.0.0.1:8801")

    assert client.automation_timeout_seconds >= 300
    assert client.status_timeout_seconds <= 30


def test_worker_returns_structured_platform_blocker_from_prepare_stage() -> None:
    runtime = BlockedPreparationRuntime()

    result = asyncio.run(runtime.process_messages(Platform.BOSS))

    assert result["accepted"] is False
    assert result["processed"] == 0
    assert result["stage"] == "boss_security_warning"
    assert result["nextAction"] == "blocked"
    assert result["decision"]["failureReason"] == "boss_security_warning"


def test_worker_process_messages_excludes_prior_contact_and_returns_selected_id() -> None:
    runtime = ExcludingContactRuntime()

    result = asyncio.run(
        runtime.process_messages(Platform.JOB51, exclude_ids={"row-a"})
    )

    assert runtime.seen_inputs == [{"row-a"}]
    assert result["processed"] == 1
    assert result["conversationId"] == "candidate-detail-b"
    assert result["selectedConversationId"] == "row-b"


def test_worker_reuses_message_preparation_within_same_batch() -> None:
    runtime = BatchPreparationRuntime(["row-a", "row-b"])

    first = asyncio.run(runtime.process_messages(Platform.JOB51, batch_id="batch-a"))
    second = asyncio.run(runtime.process_messages(Platform.JOB51, batch_id="batch-a"))

    assert first["selectedConversationId"] == "row-a"
    assert second["selectedConversationId"] == "row-b"
    assert runtime.prepare_calls == 1


def test_worker_refreshes_once_before_declaring_same_batch_drained() -> None:
    runtime = BatchPreparationRuntime(["row-a"])

    asyncio.run(runtime.process_messages(Platform.JOB51, batch_id="batch-a"))
    drained = asyncio.run(runtime.process_messages(Platform.JOB51, batch_id="batch-a"))

    assert drained["processed"] == 0
    assert runtime.prepare_calls == 2
    assert runtime.find_calls == 3


def test_worker_prepares_again_for_new_batch() -> None:
    runtime = BatchPreparationRuntime(["row-a", "row-b"])

    asyncio.run(runtime.process_messages(Platform.JOB51, batch_id="batch-a"))
    second = asyncio.run(runtime.process_messages(Platform.JOB51, batch_id="batch-b"))

    assert second["selectedConversationId"] == "row-b"
    assert runtime.prepare_calls == 2


def test_control_plane_forwards_excluded_conversation_ids() -> None:
    account_manager = AccountManager()
    owner = account_manager.workers[0].owner
    tracking_client = ExclusionTrackingWorkerClient()
    dispatcher = Dispatcher(
        account_manager=account_manager,
        clients={owner: tracking_client},
    )
    app = create_app(dispatcher=dispatcher)

    with TestClient(app) as client:
        response = client.post(
            "/automation/job51/process-messages",
            params=[
                ("owner", owner),
                ("exclude_conversation_id", "row-a"),
                ("exclude_conversation_id", "row-b"),
                ("batch_id", "run-123"),
            ],
        )

    assert response.status_code == 200
    assert tracking_client.exclude_ids == {"row-a", "row-b"}
    assert tracking_client.batch_id == "run-123"


def test_job51_generic_visible_attachment_href_downloads_for_any_owner() -> None:
    """51 通用可见附件 href 真实下载对任意账号生效，预览文字仍拒绝。"""

    pdf = b"%PDF-1.7\nbody\n%%EOF"
    page = _job51_resume_page(resume_href="https://download/resume.pdf", resume_href_bytes=pdf)
    adapter = Job51Adapter(page, owner="宋峰峰")
    result = asyncio.run(adapter.request_resume())
    assert result["downloaded"] is True
    assert result["resumeReceived"] is True

    preview_page = _job51_resume_page(preview_only=True)
    preview_adapter = Job51Adapter(preview_page, owner="宋峰峰")
    preview = asyncio.run(preview_adapter.request_resume())
    assert preview["downloaded"] is False
    assert preview["reason"] == "online_resume_not_exportable_attachment_requested"
    assert preview["onlineResumeFailure"]["reason"] == "online_resume_entry_not_found"


class SerialTracker:
    """记录并发度。"""

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0


class TrackingWorkerClient:
    """验证 dispatcher 串行调用的 worker client。"""

    def __init__(self, owner: str, tracker: SerialTracker) -> None:
        self.owner = owner
        self.tracker = tracker

    async def status(self) -> dict[str, Any]:
        return {"owner": self.owner, "status": "ready"}

    async def process_messages(
        self,
        platform: Platform,
        *,
        exclude_ids: set[str] | None = None,
        batch_id: str = "",
    ) -> dict[str, Any]:
        _ = exclude_ids, batch_id
        self.tracker.active += 1
        self.tracker.max_active = max(self.tracker.max_active, self.tracker.active)
        await asyncio.sleep(0)
        self.tracker.active -= 1
        return {"owner": self.owner, "platform": platform.value}

    async def proactive_contact(
        self, platform: Platform, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        _ = payload
        return {"owner": self.owner, "platform": platform.value}

    async def pause(self, platform: Platform) -> dict[str, Any]:
        return {"owner": self.owner, "platform": platform.value, "paused": True}


class ExclusionTrackingWorkerClient:
    def __init__(self) -> None:
        self.exclude_ids: set[str] = set()
        self.batch_id = ""

    async def process_messages(
        self,
        platform: Platform,
        *,
        exclude_ids: set[str] | None = None,
        batch_id: str = "",
    ) -> dict[str, Any]:
        self.exclude_ids = set(exclude_ids or set())
        self.batch_id = batch_id
        return {"platform": platform.value, "processed": 0}


class DuplicateContactRuntime(WorkerRuntime):
    def __init__(self) -> None:
        super().__init__(owner="和新红", port=8801, cdp_port=9222)
        self.refs = [
            ConversationRef(Platform.JOB51, "和新红", "ref-a"),
            ConversationRef(Platform.JOB51, "和新红", "ref-stale"),
            ConversationRef(Platform.JOB51, "和新红", "ref-b"),
        ]
        self.states = [
            {"conversation_id": "candidate-a", "next_action": "request_resume", "stage": "one"},
            {"conversation_id": "candidate-a", "next_action": "request_resume", "stage": "stale"},
            {"conversation_id": "candidate-b", "next_action": "request_resume", "stage": "two"},
        ]

    async def start(self) -> None:
        self.agent_ready = True

    def _adapter(self, platform: Platform) -> object:
        _ = platform
        return object()

    async def _prepare_message_adapter(self, adapter: object) -> None:
        _ = adapter

    async def _find_next_unread_thread(
        self,
        adapter: object,
        seen: set[str],
    ) -> ConversationRef | None:
        _ = adapter
        while self.refs:
            ref = self.refs.pop(0)
            if ref.conversation_id not in seen:
                return ref
        return None

    async def _run_current_conversation(self, adapter: object) -> dict[str, object]:
        _ = adapter
        return self.states.pop(0)

    async def _graph_stage(self, state: dict[str, object]) -> str:
        _ = state
        return "rules_loaded"


class BlockedPreparationRuntime(WorkerRuntime):
    def __init__(self) -> None:
        super().__init__(owner="和新红", port=8801, cdp_port=9222)

    async def start(self) -> None:
        self.agent_ready = True

    def _adapter(self, platform: Platform) -> BlockedPreparationAdapter:
        _ = platform
        return BlockedPreparationAdapter()


class ExcludingContactRuntime(WorkerRuntime):
    def __init__(self) -> None:
        super().__init__(owner="owner", port=8801, cdp_port=9222)
        self.refs = [
            ConversationRef(Platform.JOB51, "owner", "row-a"),
            ConversationRef(Platform.JOB51, "owner", "row-b"),
        ]
        self.seen_inputs: list[set[str]] = []

    async def start(self) -> None:
        self.agent_ready = True

    def _adapter(self, platform: Platform) -> object:
        _ = platform
        return object()

    async def _prepare_message_adapter(self, adapter: object) -> None:
        _ = adapter

    async def _find_next_unread_thread(
        self,
        adapter: object,
        seen: set[str],
    ) -> ConversationRef | None:
        _ = adapter
        self.seen_inputs.append(set(seen))
        return next(
            (ref for ref in self.refs if ref.conversation_id not in seen),
            None,
        )

    async def _run_current_conversation(self, adapter: object) -> dict[str, object]:
        _ = adapter
        return {
            "conversation_id": "candidate-detail-b",
            "next_action": "request_resume",
            "stage": "resume_attachment_downloaded",
        }

    async def _graph_stage(self, state: dict[str, object]) -> str:
        _ = state
        return "rules_loaded"


class BatchPreparationRuntime(WorkerRuntime):
    def __init__(self, conversation_ids: list[str]) -> None:
        super().__init__(owner="owner", port=8801, cdp_port=9222)
        self.refs = [
            ConversationRef(Platform.JOB51, "owner", conversation_id)
            for conversation_id in conversation_ids
        ]
        self.prepare_calls = 0
        self.find_calls = 0
        self.current_ref = ""

    async def start(self) -> None:
        self.agent_ready = True

    def _adapter(self, platform: Platform) -> object:
        _ = platform
        return object()

    async def _prepare_message_adapter(self, adapter: object) -> None:
        _ = adapter
        self.prepare_calls += 1

    async def _find_next_unread_thread(
        self,
        adapter: object,
        seen: set[str],
    ) -> ConversationRef | None:
        _ = adapter
        self.find_calls += 1
        ref = next(
            (item for item in self.refs if item.conversation_id not in seen),
            None,
        )
        if ref is not None:
            self.refs.remove(ref)
            self.current_ref = ref.conversation_id
        return ref

    async def _run_current_conversation(self, adapter: object) -> dict[str, object]:
        _ = adapter
        return {
            "conversation_id": f"detail-{self.current_ref}",
            "next_action": "wait",
            "stage": "handled",
        }

    async def _graph_stage(self, state: dict[str, object]) -> str:
        _ = state
        return "rules_loaded"


class BlockedPreparationAdapter:
    async def open_chat_page(self) -> None:
        return None

    async def select_unread_filter(self) -> dict[str, object]:
        return {"ready": False, "reason": "boss_security_warning"}

    async def select_positions(self, positions: object) -> None:
        _ = positions


def _runtime_clients() -> dict[str, InProcessWorkerClient]:
    return {
        "和新红": InProcessWorkerClient(
            WorkerRuntime(owner="和新红", port=8801, cdp_port=9222)
        ),
        "宋峰峰": InProcessWorkerClient(
            WorkerRuntime(owner="宋峰峰", port=8802, cdp_port=9223)
        ),
    }


def _job51_resume_page(**extra: object):
    from app.browser.fake_page import FakePage

    convo = {
        "id": "resume-conv",
        "name": "候选人",
        "position": "销售管培生",
        "label": "候选人 销售管培生",
        "latest_message": "已发简历",
        "unread_count": 1,
        "messages": [{"sender": "other", "text": "已发简历"}],
        **extra,
    }
    return FakePage(conversations=[convo])
