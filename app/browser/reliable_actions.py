"""平台无关的可靠动作层。

本模块只做确定性点击与校验：等待可点、执行动作、校验生效、有限重试、
结构化返回。它不判断 dry-run，也不模拟鼠标轨迹或真人行为。
"""

from __future__ import annotations

import random

from app.browser.base import BrowserElement, BrowserPage
from app.browser.interaction_profile import InteractionProfile, load_interaction_profile
from app.browser.reliable_support import (
    SCROLL_JS,
    VerifyCallback,
    last_reason,
    record_result,
    result_dict,
    scroll_position,
    sleep_ms,
    verify_filled,
    verify_once,
    wait_verified,
)


async def reliable_click(
    page: BrowserPage,
    selector: str,
    *,
    label: str = "",
    verify: VerifyCallback | None = None,
    profile: InteractionProfile | None = None,
) -> dict[str, object]:
    """可靠点击 selector：等待、点击、校验、有限重试。"""

    profile = profile or load_interaction_profile()
    attempts: list[dict[str, object]] = []
    max_attempts = max(1, profile.max_retries)
    for attempt in range(1, max_attempts + 1):
        preverified = await verify_once(verify)
        if attempt > 1 and preverified["verified"]:
            result = result_dict(
                True,
                "click",
                label,
                selector=selector,
                attempts=attempts,
                verified=True,
                reason="verified_before_retry",
            )
            record_result(page, result)
            return result
        await _throttle(page, profile)
        ready = await page.wait_for(selector, timeout_ms=profile.click_timeout_ms)
        if not ready:
            attempts.append({"attempt": attempt, "clicked": False, "reason": "not_clickable"})
            await _retry_backoff(page, profile, attempt)
            continue
        try:
            clicked = await page.click(selector, timeout_ms=profile.click_timeout_ms)
        except Exception as error:
            attempts.append(
                {
                    "attempt": attempt,
                    "clicked": False,
                    "reason": "click_error",
                    "error": str(error),
                }
            )
            await _retry_backoff(page, profile, attempt)
            continue
        await _post_action_wait(page, profile)
        verified = await wait_verified(page, verify, profile.verify_timeout_ms)
        attempts.append(
            {
                "attempt": attempt,
                "clicked": bool(clicked),
                "verified": bool(verified["verified"]),
                "reason": verified.get("reason", ""),
            }
        )
        if clicked and verified["verified"]:
            result = result_dict(
                True,
                "click",
                label,
                selector=selector,
                attempts=attempts,
                verified=True,
            )
            record_result(page, result)
            return result
        await _retry_backoff(page, profile, attempt)
    result = result_dict(
        False,
        "click",
        label,
        selector=selector,
        attempts=attempts,
        verified=False,
        reason=last_reason(attempts, "click_not_verified"),
    )
    record_result(page, result)
    return result


async def reliable_click_element(
    page: BrowserPage,
    element: BrowserElement,
    *,
    label: str = "",
    verify: VerifyCallback | None = None,
    profile: InteractionProfile | None = None,
) -> dict[str, object]:
    """可靠点击已找到的元素。"""

    profile = profile or load_interaction_profile()
    attempts: list[dict[str, object]] = []
    max_attempts = max(1, profile.max_retries)
    for attempt in range(1, max_attempts + 1):
        preverified = await verify_once(verify)
        if attempt > 1 and preverified["verified"]:
            result = result_dict(
                True,
                "click_element",
                label,
                attempts=attempts,
                verified=True,
                reason="verified_before_retry",
            )
            record_result(page, result)
            return result
        await _throttle(page, profile)
        try:
            await element.click(timeout_ms=profile.click_timeout_ms)
        except Exception as error:
            attempts.append(
                {
                    "attempt": attempt,
                    "clicked": False,
                    "reason": "click_error",
                    "error": str(error),
                }
            )
            await _retry_backoff(page, profile, attempt)
            continue
        await _post_action_wait(page, profile)
        verified = await wait_verified(page, verify, profile.verify_timeout_ms)
        attempts.append(
            {
                "attempt": attempt,
                "clicked": True,
                "verified": bool(verified["verified"]),
                "reason": verified.get("reason", ""),
            }
        )
        if verified["verified"]:
            result = result_dict(
                True,
                "click_element",
                label,
                attempts=attempts,
                verified=True,
            )
            record_result(page, result)
            return result
        await _retry_backoff(page, profile, attempt)
    result = result_dict(
        False,
        "click_element",
        label,
        attempts=attempts,
        verified=False,
        reason=last_reason(attempts, "click_not_verified"),
    )
    record_result(page, result)
    return result


async def reliable_fill(
    page: BrowserPage,
    selector: str,
    text: str,
    *,
    label: str = "",
    verify_value: bool = True,
    profile: InteractionProfile | None = None,
) -> dict[str, object]:
    """可靠填入文本，可选校验输入值。"""

    profile = profile or load_interaction_profile()
    await _throttle(page, profile)
    ready = await page.wait_for(selector, timeout_ms=profile.click_timeout_ms)
    if not ready:
        result = result_dict(False, "fill", label, selector=selector, reason="not_fillable")
        record_result(page, result)
        return result
    try:
        filled = await page.fill(selector, text, timeout_ms=profile.click_timeout_ms)
    except Exception as error:
        result = result_dict(
            False,
            "fill",
            label,
            selector=selector,
            reason="fill_error",
            error=str(error),
        )
        record_result(page, result)
        return result
    await _post_action_wait(page, profile)
    verified = True
    if verify_value:
        verified = await verify_filled(page, selector, text)
    result = result_dict(
        bool(filled and verified),
        "fill",
        label,
        selector=selector,
        verified=verified,
        reason="" if filled and verified else "fill_not_verified",
    )
    record_result(page, result)
    return result


async def reliable_confirm(
    page: BrowserPage,
    selector: str,
    expected_texts: tuple[str, ...] | list[str],
    *,
    label: str = "",
    verify: VerifyCallback | None = None,
    profile: InteractionProfile | None = None,
) -> dict[str, object]:
    """查找包含指定文本的确认按钮并可靠点击。"""

    expected = tuple(str(item) for item in expected_texts if str(item).strip())
    matches: list[tuple[int, BrowserElement]] = []
    for element in await page.query_all(selector):
        text = " ".join((await element.text()).split())
        if not text:
            continue
        if text in expected:
            matches.append((0, element))
        elif any(item in text for item in expected):
            matches.append((len(text), element))
    if matches:
        _, element = sorted(matches, key=lambda item: item[0])[0]
        return await reliable_click_element(
            page,
            element,
            label=label or "confirm",
            verify=verify,
            profile=profile,
        )
    result = result_dict(
        False, "confirm", label or "confirm", selector=selector, reason="not_found"
    )
    record_result(page, result)
    return result


async def reliable_scroll(
    page: BrowserPage,
    *,
    amount: int = 600,
    container_selector: str = "",
    max_segments: int = 20,
    profile: InteractionProfile | None = None,
) -> dict[str, object]:
    """用分段滚动触发懒加载，避免一次性瞬移漏加载。"""

    profile = profile or load_interaction_profile()
    total = int(amount)
    if total == 0:
        return result_dict(True, "scroll", "scroll", reason="zero_amount")
    direction = 1 if total > 0 else -1
    remaining = abs(total)
    segments: list[int] = []
    while remaining > 0 and len(segments) < max_segments:
        low, high = profile.scroll_segment_px
        step = min(remaining, random.randint(low, high))
        segments.append(direction * step)
        remaining -= step
    before = await scroll_position(page, container_selector)
    for step in segments:
        await page.eval_js(
            SCROLL_JS,
            {"selector": container_selector, "amount": step},
        )
        await sleep_ms(page, random.randint(*profile.scroll_step_ms), profile)
    await _post_action_wait(page, profile)
    after = await scroll_position(page, container_selector)
    result = result_dict(
        True,
        "scroll",
        "scroll",
        segments=segments,
        before=before,
        after=after,
        scrolled=before != after or bool(segments),
    )
    record_result(page, result)
    return result


async def _throttle(page: BrowserPage, profile: InteractionProfile) -> None:
    await sleep_ms(page, random.randint(*profile.throttle_ms), profile)


async def _retry_backoff(
    page: BrowserPage,
    profile: InteractionProfile,
    attempt: int,
) -> None:
    low, high = profile.retry_backoff_ms
    await sleep_ms(page, random.randint(low, high) * max(1, attempt), profile)


async def _post_action_wait(page: BrowserPage, profile: InteractionProfile) -> None:
    """真实页面每个动作结束后至少等待 1 秒再检测。"""

    await sleep_ms(page, max(1000, profile.post_action_wait_ms), profile)
