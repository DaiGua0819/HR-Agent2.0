"""平台标签页与登录态上下文。"""

from __future__ import annotations


def resolve_platform_page(platform: str) -> object:
    """返回指定平台的标签页句柄。"""

    raise NotImplementedError(f"Phase 1+ 接入标签页上下文: {platform}")
