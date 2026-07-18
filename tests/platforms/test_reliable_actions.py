"""可靠动作层的离线测试。

这些测试只使用 FakePage，确保可靠点击层不依赖真实浏览器，也不会把重试写成
重复副作用点击。
"""

from __future__ import annotations

import asyncio

from app.browser.fake_page import FakeElement, FakePage
from app.browser.interaction_profile import InteractionProfile
from app.browser.reliable_actions import (
    reliable_click,
    reliable_click_element,
    reliable_fill,
    reliable_scroll,
)

TEST_PROFILE = InteractionProfile(
    name="test",
    enabled=False,
    throttle_ms=(0, 0),
    click_timeout_ms=1,
    verify_timeout_ms=1,
    post_action_wait_ms=1000,
    max_retries=3,
    retry_backoff_ms=(0, 0),
    scroll_segment_px=(20, 20),
    scroll_step_ms=(0, 0),
)


def test_reliable_click_records_success_on_fake_page() -> None:
    """selector 点击成功后写入结构化动作记录。"""

    page = FakePage()

    async def verify() -> bool:
        return page.unread_selected

    result = asyncio.run(
        reliable_click(
            page,
            ".filter-item",
            label="选择未读",
            verify=verify,
            profile=TEST_PROFILE,
        )
    )

    assert result["ok"] is True
    assert page.unread_selected is True
    assert page.reliable_actions[-1]["label"] == "选择未读"


def test_reliable_click_without_verifier_clicks_once_and_succeeds() -> None:
    """可选校验缺省时，点击成功本身就是完成条件。"""

    page = FakePage()

    result = asyncio.run(
        reliable_click(
            page,
            ".menu-item-all",
            label="全部职位",
            profile=TEST_PROFILE,
        )
    )

    assert result["ok"] is True
    assert page.clicks == [".menu-item-all"]


def test_reliable_click_element_without_verifier_clicks_once_and_succeeds() -> None:
    """元素点击未配置校验时不得因为重试产生重复副作用。"""

    page = FakePage()
    element = FakeElement(page, "button:confirm", "确定")

    result = asyncio.run(
        reliable_click_element(
            page,
            element,
            label="确认",
            profile=TEST_PROFILE,
        )
    )

    assert result["ok"] is True
    assert page.clicks == ["button:confirm"]


def test_reliable_click_element_preverifies_before_retry_without_duplicate_click() -> None:
    """第一次点击已生效但验证延迟时，重试前验证成功就不再点击。"""

    page = FakePage()
    element = FakeElement(page, "conversation:0", "候选人", {"index": "0"})
    verify_calls = 0

    async def verify() -> bool:
        nonlocal verify_calls
        verify_calls += 1
        return verify_calls >= 3

    result = asyncio.run(
        reliable_click_element(
            page,
            element,
            label="打开候选人",
            verify=verify,
            profile=TEST_PROFILE,
        )
    )

    assert result["ok"] is True
    assert result["reason"] == "verified_before_retry"
    assert page.clicks == ["conversation:0"]
    assert page.reliable_actions[-1]["reason"] == "verified_before_retry"


def test_reliable_fill_verifies_value_on_fake_page() -> None:
    """填入文本后读取输入框内容校验。"""

    page = FakePage()

    result = asyncio.run(
        reliable_fill(
            page,
            "textarea",
            "你好，可以看看简历吗",
            label="聊天输入",
            profile=TEST_PROFILE,
        )
    )

    assert result["ok"] is True
    assert page.input_text == "你好，可以看看简历吗"
    assert page.reliable_actions[-1]["action"] == "fill"


def test_reliable_scroll_segments_without_real_browser() -> None:
    """分段滚动在 FakePage 下不会休眠或依赖真实 DOM。"""

    page = FakePage()

    result = asyncio.run(reliable_scroll(page, amount=60, profile=TEST_PROFILE))

    assert result["ok"] is True
    assert result["segments"] == [20, 20, 20]
    assert page.reliable_actions[-1]["action"] == "scroll"
