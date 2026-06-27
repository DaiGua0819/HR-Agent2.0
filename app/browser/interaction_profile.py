"""可靠动作层的轻量交互参数。

本模块只保存节流、超时、重试和分段滚动参数，不包含鼠标轨迹、
阅读停顿、错字模拟或任何平台业务判断。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.settings import load_settings


@dataclass(frozen=True)
class InteractionProfile:
    """可靠动作层运行参数。"""

    name: str
    enabled: bool
    throttle_ms: tuple[int, int]
    click_timeout_ms: int
    verify_timeout_ms: int
    post_action_wait_ms: int
    max_retries: int
    retry_backoff_ms: tuple[int, int]
    scroll_segment_px: tuple[int, int]
    scroll_step_ms: tuple[int, int]


PROFILES: dict[str, InteractionProfile] = {
    "fast": InteractionProfile(
        name="fast",
        enabled=True,
        throttle_ms=(60, 150),
        click_timeout_ms=4000,
        verify_timeout_ms=3000,
        post_action_wait_ms=1000,
        max_retries=2,
        retry_backoff_ms=(120, 280),
        scroll_segment_px=(180, 320),
        scroll_step_ms=(35, 110),
    ),
    "normal": InteractionProfile(
        name="normal",
        enabled=True,
        throttle_ms=(150, 400),
        click_timeout_ms=6000,
        verify_timeout_ms=4000,
        post_action_wait_ms=1000,
        max_retries=3,
        retry_backoff_ms=(220, 520),
        scroll_segment_px=(120, 260),
        scroll_step_ms=(55, 235),
    ),
    "slow": InteractionProfile(
        name="slow",
        enabled=True,
        throttle_ms=(350, 800),
        click_timeout_ms=8000,
        verify_timeout_ms=5000,
        post_action_wait_ms=1000,
        max_retries=3,
        retry_backoff_ms=(420, 900),
        scroll_segment_px=(90, 190),
        scroll_step_ms=(90, 320),
    ),
}


def get_interaction_profile(
    name: str | None = None,
    *,
    enabled: bool | None = None,
) -> InteractionProfile:
    """按名称返回交互参数；未知名称回退到 normal。"""

    key = str(name or "normal").strip().lower()
    profile = PROFILES.get(key, PROFILES["normal"])
    if enabled is None:
        return profile
    return replace(profile, enabled=bool(enabled))


def load_interaction_profile() -> InteractionProfile:
    """从 settings/env 读取当前可靠动作层配置。"""

    settings = load_settings()
    return get_interaction_profile(
        settings.interaction_profile,
        enabled=settings.interaction_enabled,
    )
