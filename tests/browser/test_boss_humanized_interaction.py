from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from app.browser.humanized_pointer import (
    DEFAULT_HUMANIZED_PROFILE,
    humanized_click_element,
)
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
    ) -> None:
        self.raw_page = raw_page
        self.box = box
        self.input_element = input_element

    async def scroll_into_view_if_needed(self, timeout: int | None = None) -> None:
        self.raw_page.events.append(("scroll_into_view", timeout))

    async def bounding_box(self) -> dict[str, float]:
        return dict(self.box)

    async def focus(self, timeout: int | None = None) -> None:
        self.raw_page.events.append(("focus", timeout))

    async def evaluate(self, script: str) -> str:
        _ = script
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


async def _verified(value: bool) -> dict[str, object]:
    return {"verified": value}


def _inside(box: dict[str, float], x: float, y: float) -> bool:
    return box["x"] <= x <= box["x"] + box["width"] and box["y"] <= y <= box["y"] + box["height"]
