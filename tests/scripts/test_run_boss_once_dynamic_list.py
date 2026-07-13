from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from app.platforms.boss import row_click
from app.platforms.boss.row_click import find_row_for_state

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from scripts import run_boss_once


class Row:
    def __init__(self, row_id: str, label: str) -> None:
        self.row_id = row_id
        self.label = label

    async def attr(self, name: str) -> str:
        return self.row_id if name in {"id", "data-id", "data-uid"} else ""

    async def text(self) -> str:
        return self.label


class RowPage:
    def __init__(self, rows: list[Row]) -> None:
        self.rows = rows

    async def query_all(self, selector: str) -> list[Row]:
        _ = selector
        return self.rows


class StableLocator:
    def __init__(self, selector: str) -> None:
        self.selector = selector
        self.kind = "stable"

    @property
    def first(self) -> StableLocator:
        return self

    async def count(self) -> int:
        return 1

    async def is_visible(self) -> bool:
        return True

    async def inner_text(self) -> str:
        return "范祚淳 AI应用开发实习生"

    async def get_attribute(self, name: str) -> str:
        return "_638190971-0" if name == "id" else ""


class StableRawPage:
    def __init__(self) -> None:
        self.selectors: list[str] = []

    def locator(self, selector: str) -> StableLocator:
        self.selectors.append(selector)
        return StableLocator(selector)


class DynamicLocatorPage(RowPage):
    def __init__(self) -> None:
        dynamic = Row("_638190971-0", "范祚淳 AI应用开发实习生")
        dynamic.locator = SimpleNamespace(kind="nth")
        super().__init__([dynamic])
        self.page = StableRawPage()


class Adapter:
    def __init__(self) -> None:
        self.page = SimpleNamespace(reliable_actions=[])

    async def select_positions(self, positions: object) -> None:
        _ = positions


class ReadyPage:
    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> bool:
        _ = selector, timeout_ms
        return True


def _state(row_id: str, name: str, position: str = "AI应用开发实习生") -> dict[str, object]:
    return {
        "id": row_id,
        "index": 0,
        "name": name,
        "position": position,
        "label": f"1\n07月13日\n{name}\n{position}\n你好",
        "unread_count": 1,
    }


def _runner_state(row_id: str, name: str) -> dict[str, object]:
    return {
        "session_id": f"session-{row_id}",
        "conversation_id": row_id,
        "candidate": {"name": name},
        "applied_position": "AI应用开发实习生",
        "next_action": "wait",
        "stage": "last_message_not_candidate",
        "messages": [],
        "decision": {},
    }


def test_live_row_lookup_never_uses_stale_index_for_another_candidate() -> None:
    page = RowPage([Row("_current-id", "当前联系人 AI应用开发实习生")])

    found = asyncio.run(
        find_row_for_state(
            page,
            {
                "id": "_missing-id",
                "index": 0,
                "label": "原目标 AI应用开发实习生",
            },
        )
    )

    assert found is None


def test_live_row_lookup_rebinds_exact_id_to_stable_locator() -> None:
    page = DynamicLocatorPage()

    found = asyncio.run(
        find_row_for_state(
            page,
            _state("_638190971-0", "范祚淳"),
        )
    )

    assert found is not None
    assert found.locator.kind == "stable"
    assert "638190971-0" in found.locator.selector
    assert page.page.selectors


def test_click_row_state_relocates_exact_id_before_second_attempt(monkeypatch) -> None:
    page = SimpleNamespace(reliable_actions=[])
    state = _state("_638190971-0", "范祚淳")
    rows = [SimpleNamespace(locator="first"), SimpleNamespace(locator="second")]
    located: list[object] = []

    async def find_row(page_arg: object, state_arg: dict[str, object]) -> object:
        _ = page_arg, state_arg
        row = rows[len(located)]
        located.append(row)
        return row

    async def safe_target(row: object) -> tuple[object, str]:
        return row, "stable-id"

    async def click(page_arg: object, element: object, **kwargs: object) -> dict[str, object]:
        _ = page_arg, kwargs
        if element is rows[0]:
            return {"ok": False, "reason": "target_moved_before_mouse_down"}
        return {"ok": True}

    monkeypatch.setattr(row_click, "find_row_for_state", find_row)
    monkeypatch.setattr(row_click, "_safe_row_click_target", safe_target)
    monkeypatch.setattr(row_click, "boss_click_conversation_row", click)

    result = asyncio.run(row_click.click_row_state(page, state))

    assert result["ok"] is True
    assert located == rows


def test_process_boss_refreshes_unread_rows_after_each_candidate(monkeypatch) -> None:
    first = _state("_first", "第一位")
    second = _state("_second", "第二位")
    row_batches = [[first], [second], []]
    read_calls = 0
    clicked: list[str] = []
    runner_results = [_runner_state("_first", "第一位"), _runner_state("_second", "第二位")]

    async def read_rows(page: object) -> list[dict[str, object]]:
        nonlocal read_calls
        _ = page
        result = row_batches[min(read_calls, len(row_batches) - 1)]
        read_calls += 1
        return result

    async def find_row(page: object, state: dict[str, object]) -> Row:
        _ = page
        return Row(str(state["id"]), str(state["label"]))

    async def click_row(
        page: object,
        state: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        _ = page, kwargs
        clicked.append(str(state["id"]))
        return {"ok": True}

    async def wait_context(adapter: object) -> SimpleNamespace:
        _ = adapter
        return SimpleNamespace(
            candidate=SimpleNamespace(name="候选人", applied_position="AI应用开发实习生"),
            messages=[],
        )

    class Runner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = args, kwargs

        async def run_current(self) -> dict[str, object]:
            return runner_results.pop(0)

    monkeypatch.setattr(run_boss_once.boss_actions, "read_unread_row_states", read_rows)
    monkeypatch.setattr(run_boss_once, "_find_boss_row", find_row)
    monkeypatch.setattr(run_boss_once, "click_row_state", click_row)
    monkeypatch.setattr(run_boss_once, "_wait_for_context", wait_context)
    monkeypatch.setattr(run_boss_once, "ConversationRunner", Runner)

    summaries = asyncio.run(
        run_boss_once._process_boss(
            Adapter(),
            2,
            conversation_repository=object(),
            artifact_store=object(),
        )
    )

    assert clicked == ["_first", "_second"]
    assert read_calls == 2
    assert [item["conversationId"] for item in summaries] == ["_first", "_second"]


def test_process_boss_stops_immediately_after_open_failure(monkeypatch) -> None:
    first = _state("_first", "第一位")
    second = _state("_second", "第二位")
    clicked: list[str] = []

    async def read_rows(page: object) -> list[dict[str, object]]:
        _ = page
        return [first, second]

    async def find_row(page: object, state: dict[str, object]) -> Row:
        _ = page
        return Row(str(state["id"]), str(state["label"]))

    async def click_row(
        page: object,
        state: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        _ = page, kwargs
        clicked.append(str(state["id"]))
        return {
            "ok": False,
            "reason": "opened_thread_mismatch",
            "attempts": [{"verification": {"currentId": "_other"}}],
        }

    monkeypatch.setattr(run_boss_once.boss_actions, "read_unread_row_states", read_rows)
    monkeypatch.setattr(run_boss_once, "_find_boss_row", find_row)
    monkeypatch.setattr(run_boss_once, "click_row_state", click_row)
    monkeypatch.setattr(run_boss_once, "_write_open_failure_diagnostic", lambda payload: None)

    summaries = asyncio.run(
        run_boss_once._process_boss(
            Adapter(),
            5,
            conversation_repository=object(),
            artifact_store=object(),
        )
    )

    assert clicked == ["_first"]
    assert len(summaries) == 1
    assert summaries[0]["stage"] == "open_thread_failed"
    assert summaries[0]["decision"]["expected"]["id"] == "first"
    assert summaries[0]["decision"]["click"]["reason"] == "opened_thread_mismatch"


def test_process_boss_stops_immediately_after_resume_request_failure(monkeypatch) -> None:
    first = _state("_first", "第一位")
    second = _state("_second", "第二位")
    clicked: list[str] = []

    async def read_rows(page: object) -> list[dict[str, object]]:
        _ = page
        return [first, second]

    async def find_row(page: object, state: dict[str, object]) -> Row:
        _ = page
        return Row(str(state["id"]), str(state["label"]))

    async def click_row(
        page: object,
        state: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        _ = page, kwargs
        clicked.append(str(state["id"]))
        return {"ok": True}

    async def wait_context(adapter: object) -> SimpleNamespace:
        _ = adapter
        return SimpleNamespace(
            candidate=SimpleNamespace(name="候选人", applied_position="AI应用开发实习生"),
            messages=[],
        )

    class Runner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = args, kwargs

        async def run_current(self) -> dict[str, object]:
            return {
                **_runner_state("_first", "第一位"),
                "next_action": "request_resume_failed",
                "stage": "request_resume_action_failed",
                "decision": {
                    "reason": "request_resume_action_failed",
                    "result": {"reason": "resume_request_confirm_failed"},
                },
            }

    monkeypatch.setattr(run_boss_once.boss_actions, "read_unread_row_states", read_rows)
    monkeypatch.setattr(run_boss_once, "_find_boss_row", find_row)
    monkeypatch.setattr(run_boss_once, "click_row_state", click_row)
    monkeypatch.setattr(run_boss_once, "_wait_for_context", wait_context)
    monkeypatch.setattr(run_boss_once, "ConversationRunner", Runner)

    summaries = asyncio.run(
        run_boss_once._process_boss(
            Adapter(),
            3,
            conversation_repository=object(),
            artifact_store=object(),
        )
    )

    assert clicked == ["_first"]
    assert len(summaries) == 1
    assert summaries[0]["action"] == "request_resume_failed"


def test_process_boss_skips_anomalies_until_threshold_is_exceeded(monkeypatch) -> None:
    first = _state("_first", "第一位")
    second = _state("_second", "第二位")
    third = _state("_third", "第三位")
    clicked: list[str] = []
    results = [
        {
            **_runner_state("_first", "第一位"),
            "next_action": "request_resume_failed",
            "stage": "request_resume_action_failed",
        },
        {
            **_runner_state("_second", "第二位"),
            "next_action": "send_failed",
            "stage": "direct_resume_prompt_send_failed",
        },
        _runner_state("_third", "第三位"),
    ]

    async def read_rows(page: object) -> list[dict[str, object]]:
        _ = page
        return [first, second, third]

    async def find_row(page: object, state: dict[str, object]) -> Row:
        _ = page
        return Row(str(state["id"]), str(state["label"]))

    async def click_row(
        page: object,
        state: dict[str, object],
        **kwargs: object,
    ) -> dict[str, object]:
        _ = page, kwargs
        clicked.append(str(state["id"]))
        return {"ok": True}

    async def wait_context(adapter: object) -> SimpleNamespace:
        _ = adapter
        return SimpleNamespace(
            candidate=SimpleNamespace(name="候选人", applied_position="AI应用开发实习生"),
            messages=[],
        )

    class Runner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = args, kwargs

        async def run_current(self) -> dict[str, object]:
            return results.pop(0)

    monkeypatch.setattr(run_boss_once.boss_actions, "read_unread_row_states", read_rows)
    monkeypatch.setattr(run_boss_once, "_find_boss_row", find_row)
    monkeypatch.setattr(run_boss_once, "click_row_state", click_row)
    monkeypatch.setattr(run_boss_once, "_wait_for_context", wait_context)
    monkeypatch.setattr(run_boss_once, "ConversationRunner", Runner)

    summaries = asyncio.run(
        run_boss_once._process_boss(
            Adapter(),
            3,
            conversation_repository=object(),
            artifact_store=object(),
            max_anomalies=1,
        )
    )

    assert clicked == ["_first", "_second"]
    assert len(summaries) == 2
    assert [item["action"] for item in summaries] == ["request_resume_failed", "send_failed"]


def test_verify_opened_thread_accepts_exact_name_after_right_header_switch(monkeypatch) -> None:
    async def read_context(page: object, *, owner: str) -> SimpleNamespace:
        _ = page, owner
        return SimpleNamespace(
            id="_different-dom-id",
            candidate=SimpleNamespace(
                name="王卓亚",
                applied_position="沟通职位： AI应用开发实习生",
            ),
        )

    monkeypatch.setattr(run_boss_once.boss_actions, "read_chat_context", read_context)

    result = asyncio.run(
        run_boss_once._verify_boss_thread_opened(
            ReadyPage(),
            _state("_captured-id", "王卓亚"),
        )
    )

    assert result["verified"] is True
    assert result["reason"] == "candidate_identity_matched"


def test_verify_opened_thread_rejects_same_name_when_position_conflicts(monkeypatch) -> None:
    async def read_context(page: object, *, owner: str) -> SimpleNamespace:
        _ = page, owner
        return SimpleNamespace(
            id="_different-dom-id",
            candidate=SimpleNamespace(
                name="王卓亚",
                applied_position="沟通职位： AI产品经理",
            ),
        )

    monkeypatch.setattr(run_boss_once.boss_actions, "read_chat_context", read_context)

    result = asyncio.run(
        run_boss_once._verify_boss_thread_opened(
            ReadyPage(),
            _state("_captured-id", "王卓亚"),
        )
    )

    assert result["verified"] is False
    assert result["reason"] == "opened_thread_mismatch"
