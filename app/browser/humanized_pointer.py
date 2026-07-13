"""Precise browser-level mouse movement and incremental text entry.

The helpers use Playwright's CDP mouse and keyboard. They do not fall back to
DOM ``click()`` calls on real pages; callers decide how an unavailable pointer
should be handled.
"""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from app.browser.reliable_support import record_result, verify_once, wait_verified

VerifyCallback = Callable[[], Awaitable[bool | dict[str, object]]]


@dataclass(frozen=True)
class HumanizedInteractionProfile:
    enabled: bool = True
    path_points: tuple[int, int] = (14, 24)
    move_step_delay_ms: tuple[int, int] = (8, 22)
    geometry_stability_ms: int = 70
    geometry_tolerance_px: float = 3.0
    hover_ms: tuple[int, int] = (90, 180)
    mouse_down_ms: tuple[int, int] = (55, 110)
    post_click_ms: tuple[int, int] = (260, 520)
    verify_timeout_ms: int = 4500
    max_click_attempts: int = 2
    key_delay_ms: tuple[int, int] = (38, 95)
    punctuation_delay_ms: tuple[int, int] = (110, 240)
    chunk_size: tuple[int, int] = (4, 8)
    chunk_pause_ms: tuple[int, int] = (100, 240)
    post_type_ms: tuple[int, int] = (280, 520)


DEFAULT_HUMANIZED_PROFILE = HumanizedInteractionProfile()

HUMANIZED_PROFILES: dict[str, HumanizedInteractionProfile] = {
    "fast": replace(
        DEFAULT_HUMANIZED_PROFILE,
        path_points=(10, 16),
        move_step_delay_ms=(5, 12),
        key_delay_ms=(24, 60),
        punctuation_delay_ms=(70, 140),
        post_click_ms=(180, 320),
        post_type_ms=(180, 320),
    ),
    "normal": DEFAULT_HUMANIZED_PROFILE,
    "slow": replace(
        DEFAULT_HUMANIZED_PROFILE,
        path_points=(18, 30),
        move_step_delay_ms=(12, 28),
        key_delay_ms=(55, 125),
        punctuation_delay_ms=(150, 320),
        post_click_ms=(380, 700),
        post_type_ms=(380, 700),
    ),
}


def get_humanized_profile(
    name: str | None = None,
    *,
    enabled: bool | None = None,
) -> HumanizedInteractionProfile:
    profile = HUMANIZED_PROFILES.get(str(name or "normal").strip().lower())
    profile = profile or DEFAULT_HUMANIZED_PROFILE
    return profile if enabled is None else replace(profile, enabled=bool(enabled))


async def humanized_click_element(
    page: Any,
    element: Any,
    *,
    label: str = "",
    verify: VerifyCallback | None = None,
    profile: HumanizedInteractionProfile = DEFAULT_HUMANIZED_PROFILE,
    rng: random.Random | None = None,
) -> dict[str, object]:
    """Move through a smooth path and click a stable point inside an element."""

    raw_page = getattr(page, "page", None)
    mouse = getattr(raw_page, "mouse", None)
    locator = getattr(element, "locator", None)
    if mouse is None or locator is None:
        return _record(
            page,
            {
                "ok": False,
                "action": "click_element",
                "label": label,
                "method": "humanized_mouse",
                "reason": "humanized_mouse_unavailable",
            },
        )

    randomizer = rng or random.Random()
    attempts: list[dict[str, object]] = []
    for attempt in range(1, max(1, profile.max_click_attempts) + 1):
        if attempt > 1 and verify is not None:
            preverified = await verify_once(verify)
            if preverified.get("verified"):
                return _record(
                    page,
                    {
                        "ok": True,
                        "action": "click_element",
                        "label": label,
                        "method": "humanized_mouse",
                        "verified": True,
                        "reason": "verified_before_retry",
                        "attempts": attempts,
                    },
                )
        try:
            await locator.scroll_into_view_if_needed(timeout=5000)
            first_box = await locator.bounding_box()
            if not _valid_box(first_box):
                attempts.append({"attempt": attempt, "reason": "target_box_unavailable"})
                continue
            await _sleep_ms(profile.geometry_stability_ms, profile)
            second_box = await locator.bounding_box()
            if not _valid_box(second_box):
                attempts.append({"attempt": attempt, "reason": "target_box_unavailable"})
                continue
            box = dict(second_box)
            moved_px = _box_distance(first_box, second_box)
            target_x, target_y = _safe_target(box, randomizer)
            start = getattr(page, "_humanized_pointer_position", None)
            if not _point(start):
                start = (
                    max(2.0, target_x - randomizer.uniform(90, 180)),
                    max(2.0, target_y - randomizer.uniform(35, 110)),
                )
            points = _bezier_path(start, (target_x, target_y), profile, randomizer)
            for x, y in points:
                await mouse.move(x, y)
                page._humanized_pointer_position = (x, y)
                await _sleep_range(profile.move_step_delay_ms, profile, randomizer)

            latest_box = await locator.bounding_box()
            if not _valid_box(latest_box) or not _inside(latest_box, target_x, target_y):
                attempts.append(
                    {
                        "attempt": attempt,
                        "reason": "target_moved_before_click",
                        "movedPx": round(moved_px, 2),
                    }
                )
                continue

            await _sleep_range(profile.hover_ms, profile, randomizer)
            await mouse.down()
            await _sleep_range(profile.mouse_down_ms, profile, randomizer)
            await mouse.up()
            await _sleep_range(profile.post_click_ms, profile, randomizer)
            verified = await wait_verified(page, verify, profile.verify_timeout_ms)
            attempt_result = {
                "attempt": attempt,
                "clicked": True,
                "verified": bool(verified.get("verified")),
                "pathPoints": len(points),
                "target": {"x": round(target_x, 2), "y": round(target_y, 2)},
                "movedPx": round(moved_px, 2),
            }
            attempts.append(attempt_result)
            if verified.get("verified"):
                return _record(
                    page,
                    {
                        "ok": True,
                        "action": "click_element",
                        "label": label,
                        "method": "humanized_mouse",
                        "verified": True,
                        "attempts": attempts,
                    },
                )
        except Exception as error:
            attempts.append(
                {"attempt": attempt, "reason": "humanized_click_error", "error": str(error)}
            )

    reason = (
        str(attempts[-1].get("reason") or "humanized_click_not_verified")
        if attempts
        else "humanized_click_not_verified"
    )
    return _record(
        page,
        {
            "ok": False,
            "action": "click_element",
            "label": label,
            "method": "humanized_mouse",
            "verified": False,
            "attempts": attempts,
            "reason": reason,
        },
    )


async def humanized_click_rect(
    page: Any,
    rect: dict[str, object],
    *,
    label: str = "",
    verify: VerifyCallback | None = None,
    profile: HumanizedInteractionProfile = DEFAULT_HUMANIZED_PROFILE,
    rng: random.Random | None = None,
) -> dict[str, object]:
    """Move and click inside a freshly measured DOM rectangle."""

    raw_page = getattr(page, "page", None)
    mouse = getattr(raw_page, "mouse", None)
    normalized = _normalized_box(rect)
    if mouse is None:
        return _record(
            page,
            {
                "ok": False,
                "action": "click_rect",
                "label": label,
                "method": "humanized_mouse",
                "reason": "humanized_mouse_unavailable",
            },
        )
    if normalized is None:
        return _record(
            page,
            {
                "ok": False,
                "action": "click_rect",
                "label": label,
                "method": "humanized_mouse",
                "reason": str(rect.get("reason") or "target_box_unavailable"),
            },
        )

    randomizer = rng or random.Random()
    target_x, target_y = _safe_target(normalized, randomizer)
    start = getattr(page, "_humanized_pointer_position", None)
    if not _point(start):
        start = (
            max(2.0, target_x - randomizer.uniform(90, 180)),
            max(2.0, target_y - randomizer.uniform(35, 110)),
        )
    try:
        points = _bezier_path(start, (target_x, target_y), profile, randomizer)
        for x, y in points:
            await mouse.move(x, y)
            page._humanized_pointer_position = (x, y)
            await _sleep_range(profile.move_step_delay_ms, profile, randomizer)
        await _sleep_range(profile.hover_ms, profile, randomizer)
        await mouse.down()
        await _sleep_range(profile.mouse_down_ms, profile, randomizer)
        await mouse.up()
        await _sleep_range(profile.post_click_ms, profile, randomizer)
        verified = await wait_verified(page, verify, profile.verify_timeout_ms)
        ok = bool(verified.get("verified"))
        return _record(
            page,
            {
                "ok": ok,
                "action": "click_rect",
                "label": label,
                "method": "humanized_mouse",
                "verified": ok,
                "reason": "" if ok else str(verified.get("reason") or "click_not_verified"),
                "pathPoints": len(points),
                "target": {"x": round(target_x, 2), "y": round(target_y, 2)},
                "rectSource": rect.get("source") or "",
            },
        )
    except Exception as error:
        return _record(
            page,
            {
                "ok": False,
                "action": "click_rect",
                "label": label,
                "method": "humanized_mouse",
                "reason": "humanized_click_error",
                "error": str(error),
            },
        )


async def humanized_type_element(
    page: Any,
    element: Any,
    text: str,
    *,
    label: str = "",
    profile: HumanizedInteractionProfile = DEFAULT_HUMANIZED_PROFILE,
    rng: random.Random | None = None,
) -> dict[str, object]:
    """Clear an input and insert text incrementally, verifying every chunk."""

    raw_page = getattr(page, "page", None)
    keyboard = getattr(raw_page, "keyboard", None)
    locator = getattr(element, "locator", None)
    if keyboard is None or locator is None:
        return _record(
            page,
            {
                "ok": False,
                "action": "type_text",
                "label": label,
                "method": "humanized_keyboard",
                "reason": "humanized_keyboard_unavailable",
            },
        )

    randomizer = rng or random.Random()
    try:
        await locator.focus(timeout=5000)
        await keyboard.press("Control+A")
        await keyboard.press("Backspace")
        if await _input_value(locator) != "":
            return _record(
                page,
                {
                    "ok": False,
                    "action": "type_text",
                    "label": label,
                    "method": "humanized_keyboard",
                    "reason": "input_clear_failed",
                },
            )

        next_chunk = randomizer.randint(*profile.chunk_size)
        for index, character in enumerate(text, start=1):
            await keyboard.insert_text(character)
            delay = (
                profile.punctuation_delay_ms
                if character in "，。！？；：,.!?;:\n"
                else profile.key_delay_ms
            )
            await _sleep_range(delay, profile, randomizer)
            if index == next_chunk or index == len(text):
                current = await _input_value(locator)
                if current != text[:index]:
                    return _record(
                        page,
                        {
                            "ok": False,
                            "action": "type_text",
                            "label": label,
                            "method": "humanized_keyboard",
                            "reason": "input_text_mismatch",
                            "expectedLength": index,
                            "actualLength": len(current),
                        },
                    )
                await _sleep_range(profile.chunk_pause_ms, profile, randomizer)
                next_chunk += randomizer.randint(*profile.chunk_size)

        await _sleep_range(profile.post_type_ms, profile, randomizer)
        current = await _input_value(locator)
        if current != text:
            return _record(
                page,
                {
                    "ok": False,
                    "action": "type_text",
                    "label": label,
                    "method": "humanized_keyboard",
                    "reason": "input_text_mismatch",
                    "expectedLength": len(text),
                    "actualLength": len(current),
                },
            )
        return _record(
            page,
            {
                "ok": True,
                "action": "type_text",
                "label": label,
                "method": "humanized_keyboard",
                "verified": True,
                "characters": len(text),
            },
        )
    except Exception as error:
        return _record(
            page,
            {
                "ok": False,
                "action": "type_text",
                "label": label,
                "method": "humanized_keyboard",
                "reason": "humanized_type_error",
                "error": str(error),
            },
        )


def _bezier_path(
    start: tuple[float, float],
    end: tuple[float, float],
    profile: HumanizedInteractionProfile,
    rng: random.Random,
) -> list[tuple[float, float]]:
    count = rng.randint(*profile.path_points)
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    distance = max(1.0, math.hypot(dx, dy))
    perpendicular_x, perpendicular_y = -dy / distance, dx / distance
    curve = min(70.0, max(12.0, distance * rng.uniform(0.08, 0.2)))
    direction = -1 if rng.random() < 0.5 else 1
    c1 = (
        sx + dx * rng.uniform(0.25, 0.4) + perpendicular_x * curve * direction,
        sy + dy * rng.uniform(0.25, 0.4) + perpendicular_y * curve * direction,
    )
    c2 = (
        sx + dx * rng.uniform(0.65, 0.82) - perpendicular_x * curve * direction * 0.45,
        sy + dy * rng.uniform(0.65, 0.82) - perpendicular_y * curve * direction * 0.45,
    )
    points: list[tuple[float, float]] = []
    for index in range(1, count + 1):
        t = index / count
        eased = t * t * (3 - 2 * t)
        inverse = 1 - eased
        x = (
            inverse**3 * sx
            + 3 * inverse**2 * eased * c1[0]
            + 3 * inverse * eased**2 * c2[0]
            + eased**3 * ex
        )
        y = (
            inverse**3 * sy
            + 3 * inverse**2 * eased * c1[1]
            + 3 * inverse * eased**2 * c2[1]
            + eased**3 * ey
        )
        points.append((x, y))
    points[-1] = end
    return points


def _safe_target(box: dict[str, float], rng: random.Random) -> tuple[float, float]:
    inset_x = min(box["width"] * 0.28, max(3.0, box["width"] / 2 - 1))
    inset_y = min(box["height"] * 0.28, max(3.0, box["height"] / 2 - 1))
    left = box["x"] + inset_x
    right = box["x"] + box["width"] - inset_x
    top = box["y"] + inset_y
    bottom = box["y"] + box["height"] - inset_y
    return rng.uniform(left, right), rng.uniform(top, bottom)


async def _input_value(locator: Any) -> str:
    value = await locator.evaluate(
        "el => ('value' in el ? el.value : (el.innerText || el.textContent || ''))"
    )
    return str(value or "").replace("\r\n", "\n")


async def _sleep_range(
    values: tuple[int, int],
    profile: HumanizedInteractionProfile,
    rng: random.Random,
) -> None:
    await _sleep_ms(rng.randint(*values), profile)


async def _sleep_ms(milliseconds: int, profile: HumanizedInteractionProfile) -> None:
    if profile.enabled and milliseconds > 0:
        await asyncio.sleep(milliseconds / 1000)


def _valid_box(value: object) -> bool:
    return (
        isinstance(value, dict)
        and float(value.get("width") or 0) > 0
        and float(value.get("height") or 0) > 0
    )


def _normalized_box(value: dict[str, object]) -> dict[str, float] | None:
    try:
        box = {
            "x": float(value.get("x") or 0),
            "y": float(value.get("y") or 0),
            "width": float(value.get("width") or 0),
            "height": float(value.get("height") or 0),
        }
    except (TypeError, ValueError):
        return None
    return box if _valid_box(box) else None


def _inside(box: dict[str, float], x: float, y: float) -> bool:
    return box["x"] <= x <= box["x"] + box["width"] and box["y"] <= y <= box["y"] + box["height"]


def _box_distance(first: dict[str, float], second: dict[str, float]) -> float:
    return math.hypot(
        float(second["x"]) - float(first["x"]),
        float(second["y"]) - float(first["y"]),
    )


def _point(value: object) -> bool:
    return isinstance(value, tuple) and len(value) == 2


def _record(page: Any, result: dict[str, object]) -> dict[str, object]:
    record_result(page, result)
    return result
