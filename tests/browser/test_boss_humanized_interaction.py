from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from app.browser.humanized_pointer import (
    DEFAULT_HUMANIZED_PROFILE,
    humanized_click_element,
)
from app.platforms.boss import interaction as boss_interaction
from app.platforms.boss.interaction import boss_type_and_send

INSTANT_PROFILE = replace(
    DEFAULT_HUMANIZED_PROFILE,
    path_points=(8, 8),
    move_step_delay_ms=(0, 0),
    geometry_stability_ms=0,
    hover_ms=(0, 0),
    mouse_down_ms=(0, 0),
    post_click_ms=(0, 0),
    key_delay_ms=(0, 0),
    punctuation_delay_ms=(0, 0),
    chunk_pause_ms=(0, 0),
    post_type_ms=(0, 0),
    verify_timeout_ms=0,
)


class RecordingMouse:
    def __init__(self, page: RawPage) -> None:
        self.page = page

    async def move(self, x: float, y: float) -> None:
        self.page.events.append(("move", round(x, 2), round(y, 2)))
        self.page.pointer = (x, y)

    async def down(self) -> None:
        self.page.events.append(("down", *self.page.pointer))

    async def up(self) -> None:
        self.page.events.append(("up",))
        x, y = self.page.pointer
        if self.page.send_box and _inside(self.page.send_box, x, y):
            self.page.sent_messages.append(self.page.input_text)
            self.page.input_text = ""

    async def wheel(self, delta_x: float, delta_y: float) -> None:
        self.page.events.append(("wheel", delta_x, delta_y))


class RecordingKeyboard:
    def __init__(self, page: RawPage) -> None:
        self.page = page
        self.select_all = False

    async def press(self, key: str) -> None:
        self.page.events.append(("press", key))
        if key == "Control+A":
            self.select_all = True
        elif key == "Backspace" and self.select_all:
            self.page.input_text = ""
            self.select_all = False

    async def insert_text(self, text: str) -> None:
        self.page.events.append(("insert", text))
        if not self.page.drop_inserted_text:
            self.page.input_text += text


class RawPage:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []
        self.pointer = (40.0, 40.0)
        self.input_text = "旧草稿"
        self.sent_messages: list[str] = []
        self.send_box: dict[str, float] | None = None
        self.drop_inserted_text = False
        self.mouse = RecordingMouse(self)
        self.keyboard = RecordingKeyboard(self)


class RecordingLocator:
    def __init__(
        self,
        raw_page: RawPage,
        box: dict[str, float],
        *,
        input_element: bool = False,
        boxes: list[dict[str, float]] | None = None,
        hit_matches: bool = True,
        in_viewport: bool = True,
        scroll_error: Exception | None = None,
    ) -> None:
        self.raw_page = raw_page
        self.box = box
        self.boxes = list(boxes or [])
        self.box_calls = 0
        self.input_element = input_element
        self.hit_matches = hit_matches
        self.in_viewport = in_viewport
        self.scroll_error = scroll_error

    async def scroll_into_view_if_needed(self, timeout: int | None = None) -> None:
        self.raw_page.events.append(("scroll_into_view", timeout))
        if self.scroll_error is not None:
            raise self.scroll_error

    async def bounding_box(self) -> dict[str, float]:
        if self.boxes:
            index = min(self.box_calls, len(self.boxes) - 1)
            self.box_calls += 1
            return dict(self.boxes[index])
        return dict(self.box)

    async def focus(self, timeout: int | None = None) -> None:
        self.raw_page.events.append(("focus", timeout))

    async def evaluate(self, script: str, arg: object | None = None) -> str | bool:
        _ = arg
        if "window.innerWidth" in script:
            return self.in_viewport
        if "elementFromPoint" in script:
            return self.hit_matches
        return self.raw_page.input_text if self.input_element else ""


class WrappedElement:
    def __init__(self, locator: RecordingLocator) -> None:
        self.locator = locator


class WrappedPage:
    def __init__(self) -> None:
        self.page = RawPage()
        self.reliable_actions: list[dict[str, object]] = []
        self.input_element = WrappedElement(
            RecordingLocator(
                self.page,
                {"x": 120, "y": 300, "width": 420, "height": 80},
                input_element=True,
            )
        )
        send_box = {"x": 560, "y": 330, "width": 90, "height": 36}
        self.page.send_box = send_box
        self.send_element = WrappedElement(RecordingLocator(self.page, send_box))

    async def query(self, selector: str) -> WrappedElement | None:
        if "contenteditable" in selector or "textarea" in selector:
            return self.input_element
        if "send" in selector or "submit" in selector:
            return self.send_element
        return None


def test_humanized_click_moves_through_multiple_points_and_clicks_inside_target() -> None:
    page = WrappedPage()
    target = WrappedElement(
        RecordingLocator(page.page, {"x": 300, "y": 160, "width": 120, "height": 44})
    )

    result = asyncio.run(
        humanized_click_element(
            page,
            target,
            label="BOSS联系人",
            profile=INSTANT_PROFILE,
        )
    )

    moves = [event for event in page.page.events if event[0] == "move"]
    assert result["ok"] is True
    assert len(moves) >= 8
    assert _inside({"x": 300, "y": 160, "width": 120, "height": 44}, moves[-1][1], moves[-1][2])
    assert [event[0] for event in page.page.events[-2:]] == ["down", "up"]


def test_humanized_click_skips_scroll_wait_for_target_already_in_viewport() -> None:
    page = WrappedPage()
    target = WrappedElement(
        RecordingLocator(
            page.page,
            {"x": 560, "y": 330, "width": 90, "height": 36},
            in_viewport=True,
            scroll_error=TimeoutError("continuously moving editor layout"),
        )
    )

    result = asyncio.run(
        humanized_click_element(
            page,
            target,
            label="BOSS发送按钮",
            profile=replace(INSTANT_PROFILE, max_click_attempts=1),
        )
    )

    assert result["ok"] is True
    assert not any(event[0] == "scroll_into_view" for event in page.page.events)


def test_boss_click_element_blocks_on_platform_security_warning() -> None:
    page = WrappedPage()
    target = WrappedElement(
        RecordingLocator(page.page, {"x": 300, "y": 160, "width": 120, "height": 44})
    )

    async def eval_js(script: str, arg: object | None = None) -> dict[str, object]:
        _ = script, arg
        return {
            "blocked": True,
            "title": "风险提示",
            "text": "不得使用任何第三方插件、外挂、软件等招聘辅助工具",
        }

    page.eval_js = eval_js  # type: ignore[attr-defined]

    result = asyncio.run(
        boss_interaction.boss_click_element(page, target, label="BOSS发送按钮")
    )

    assert result["ok"] is False
    assert result["blocked"] is True
    assert result["reason"] == "boss_security_warning"
    assert not any(event[0] == "down" for event in page.page.events)


def test_humanized_click_preverifies_before_retry_without_second_click() -> None:
    page = WrappedPage()
    target = WrappedElement(
        RecordingLocator(page.page, {"x": 300, "y": 160, "width": 120, "height": 44})
    )
    checks = 0

    async def delayed_verify() -> dict[str, object]:
        nonlocal checks
        checks += 1
        return {"verified": checks >= 2}

    result = asyncio.run(
        humanized_click_element(
            page,
            target,
            label="BOSS联系人",
            verify=delayed_verify,
            profile=INSTANT_PROFILE,
        )
    )

    assert result["ok"] is True
    assert result["reason"] == "verified_before_retry"
    assert sum(1 for event in page.page.events if event[0] == "down") == 1


def test_humanized_click_does_not_press_after_target_moves_during_hover() -> None:
    page = WrappedPage()
    original = {"x": 300, "y": 160, "width": 120, "height": 44}
    moved = {"x": 300, "y": 260, "width": 120, "height": 44}
    target = WrappedElement(
        RecordingLocator(
            page.page,
            original,
            boxes=[original, original, original, moved],
        )
    )

    result = asyncio.run(
        humanized_click_element(
            page,
            target,
            label="BOSS联系人",
            profile=replace(INSTANT_PROFILE, max_click_attempts=1),
        )
    )

    assert result["ok"] is False
    assert result["reason"] == "target_moved_before_mouse_down"
    assert not any(event[0] == "down" for event in page.page.events)


def test_humanized_click_requires_final_point_to_hit_target_element() -> None:
    page = WrappedPage()
    target = WrappedElement(
        RecordingLocator(
            page.page,
            {"x": 300, "y": 160, "width": 120, "height": 44},
            hit_matches=False,
        )
    )

    result = asyncio.run(
        humanized_click_element(
            page,
            target,
            label="BOSS联系人",
            profile=replace(INSTANT_PROFILE, max_click_attempts=1),
        )
    )

    assert result["ok"] is False
    assert result["reason"] == "target_not_at_pointer"
    assert not any(event[0] == "down" for event in page.page.events)


def test_humanized_click_runs_guard_before_pointer_hit_test() -> None:
    page = WrappedPage()
    target = WrappedElement(
        RecordingLocator(
            page.page,
            {"x": 300, "y": 160, "width": 120, "height": 44},
            hit_matches=False,
        )
    )

    async def guard() -> dict[str, object]:
        return {
            "verified": False,
            "reason": "boss_security_warning",
            "warning": {"title": "风险提示"},
        }

    result = asyncio.run(
        humanized_click_element(
            page,
            target,
            label="BOSS发送按钮",
            pre_click_guard=guard,
            profile=replace(INSTANT_PROFILE, max_click_attempts=1),
        )
    )

    assert result["ok"] is False
    assert result["reason"] == "boss_security_warning"
    assert not any(event[0] == "down" for event in page.page.events)


def test_humanized_click_cancels_when_pre_click_guard_detects_state_change() -> None:
    page = WrappedPage()
    target = WrappedElement(
        RecordingLocator(page.page, {"x": 300, "y": 160, "width": 120, "height": 44})
    )

    async def guard() -> dict[str, object]:
        return {
            "verified": False,
            "reason": "resume_request_state_changed",
            "state": {"pendingResumeConsent": True},
        }

    result = asyncio.run(
        humanized_click_element(
            page,
            target,
            label="BOSS求简历确认",
            pre_click_guard=guard,
            profile=replace(INSTANT_PROFILE, max_click_attempts=1),
        )
    )

    assert result["ok"] is False
    assert result["reason"] == "resume_request_state_changed"
    assert not any(event[0] == "down" for event in page.page.events)


def test_boss_click_element_rechecks_security_warning_before_mouse_down() -> None:
    page = WrappedPage()
    target = WrappedElement(
        RecordingLocator(page.page, {"x": 300, "y": 160, "width": 120, "height": 44})
    )
    checks = 0

    async def eval_js(script: str, arg: object | None = None) -> dict[str, object]:
        nonlocal checks
        _ = script, arg
        checks += 1
        if checks == 1:
            return {"blocked": False, "title": "", "text": ""}
        return {
            "blocked": True,
            "title": "风险提示",
            "text": "不得使用任何第三方插件、外挂、软件等招聘辅助工具",
        }

    page.eval_js = eval_js  # type: ignore[attr-defined]

    result = asyncio.run(
        boss_interaction.boss_click_element(page, target, label="BOSS发送按钮")
    )

    assert result["ok"] is False
    assert result["reason"] == "boss_security_warning"
    assert checks >= 2
    assert not any(event[0] == "down" for event in page.page.events)


def test_boss_conversation_click_waits_for_delayed_identity_switch(monkeypatch) -> None:
    page = WrappedPage()
    target = WrappedElement(
        RecordingLocator(page.page, {"x": 300, "y": 160, "width": 120, "height": 44})
    )
    checks = 0

    async def delayed_verify() -> dict[str, object]:
        nonlocal checks
        checks += 1
        return {
            "verified": checks >= 3,
            "reason": "conversation_id_matched" if checks >= 3 else "opened_thread_mismatch",
        }

    monkeypatch.setattr(boss_interaction, "_boss_profile", lambda: INSTANT_PROFILE)

    result = asyncio.run(
        boss_interaction.boss_click_conversation_row(
            page,
            target,
            label="BOSS候选人会话",
            verify=delayed_verify,
        )
    )

    assert result["ok"] is True
    assert checks >= 3
    assert sum(1 for event in page.page.events if event[0] == "down") == 1


def test_boss_type_and_send_finishes_exact_text_before_send_click() -> None:
    page = WrappedPage()
    message = "你好，方便发一份简历吗"

    result = asyncio.run(
        boss_type_and_send(
            page,
            message,
            verify_sent=lambda: _verified(page.page.sent_messages == [message]),
            profile=INSTANT_PROFILE,
        )
    )

    events = page.page.events
    last_insert = max(index for index, event in enumerate(events) if event[0] == "insert")
    send_down = max(index for index, event in enumerate(events) if event[0] == "down")
    inserted = "".join(str(event[1]) for event in events if event[0] == "insert")
    assert result["ok"] is True
    assert inserted == message
    assert last_insert < send_down
    assert page.page.sent_messages == [message]


def test_boss_type_and_send_blocks_send_when_input_does_not_match() -> None:
    page = WrappedPage()
    page.page.drop_inserted_text = True

    result = asyncio.run(
        boss_type_and_send(
            page,
            "不会被发送",
            verify_sent=lambda: _verified(False),
            profile=INSTANT_PROFILE,
        )
    )

    assert result["ok"] is False
    assert result["reason"] == "input_text_mismatch"
    assert page.page.sent_messages == []
    assert not any(
        event[0] == "down" and _inside(page.page.send_box or {}, float(event[1]), float(event[2]))
        for event in page.page.events
    )


def test_boss_type_and_send_blocks_when_conversation_changes() -> None:
    page = WrappedPage()

    result = asyncio.run(
        boss_type_and_send(
            page,
            "已经完整输入但不能发错人",
            verify_sent=lambda: _verified(False),
            expected_conversation=lambda: _verified(False),
            profile=INSTANT_PROFILE,
        )
    )

    assert result["ok"] is False
    assert result["reason"] == "conversation_changed_before_send"
    assert page.page.sent_messages == []
    assert not any(
        event[0] == "down" and _inside(page.page.send_box or {}, float(event[1]), float(event[2]))
        for event in page.page.events
    )


def test_boss_send_button_is_never_clicked_twice_when_verification_fails() -> None:
    page = WrappedPage()

    result = asyncio.run(
        boss_type_and_send(
            page,
            "只允许点击一次发送",
            verify_sent=lambda: _verified(False),
            profile=INSTANT_PROFILE,
        )
    )

    send_clicks = [
        event
        for event in page.page.events
        if event[0] == "down"
        and _inside(page.page.send_box or {}, float(event[1]), float(event[2]))
    ]
    assert result["ok"] is False
    assert len(send_clicks) == 1


def test_boss_send_verification_waits_eight_seconds_but_clicks_once(monkeypatch) -> None:
    page = WrappedPage()
    send_profiles = []

    async def click_element(
        wrapped_page,
        element,
        *,
        label,
        verify=None,
        profile=None,
    ):
        _ = element, verify
        if "发送按钮" in label:
            send_profiles.append(profile)
            wrapped_page.page.sent_messages.append("测试消息")
        return {"ok": True}

    monkeypatch.setattr(boss_interaction, "_boss_profile", lambda: INSTANT_PROFILE)
    monkeypatch.setattr(boss_interaction, "boss_click_element", click_element)

    result = asyncio.run(
        boss_interaction.boss_type_and_send(
            page,
            "测试消息",
            verify_sent=lambda: _verified(True),
        )
    )

    assert result["ok"] is True
    assert len(send_profiles) == 1
    assert send_profiles[0].verify_timeout_ms == 8000
    assert send_profiles[0].max_click_attempts == 1


def test_boss_message_entrypoints_do_not_use_locator_click_layer() -> None:
    root = Path(__file__).resolve().parents[2]
    entrypoints = (
        root / "app" / "platforms" / "boss" / "actions.py",
        root / "app" / "platforms" / "boss" / "actions_resume.py",
        root / "app" / "platforms" / "boss" / "row_click.py",
        root / "scripts" / "run_boss_once.py",
        root / "scripts" / "boss_targeting.py",
    )

    for path in entrypoints:
        source = path.read_text(encoding="utf-8")
        assert "from app.browser.reliable_actions import" not in source, path

    resume_source = entrypoints[1].read_text(encoding="utf-8")
    assert "dispatchEvent(new" not in resume_source
    assert "typeof el.click" not in resume_source


async def _verified(value: bool) -> dict[str, object]:
    return {"verified": value}


def _inside(box: dict[str, float], x: float, y: float) -> bool:
    return box["x"] <= x <= box["x"] + box["width"] and box["y"] <= y <= box["y"] + box["height"]
