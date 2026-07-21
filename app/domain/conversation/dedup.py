"""会话消息去重与最近消息指纹。"""

from __future__ import annotations

import hashlib

from app.platforms.types import ChatMessage


def normalize_message_text(value: str) -> str:
    """规整消息文本，用于去重和身份校验。"""

    return " ".join(str(value or "").split())


def message_hash(message: ChatMessage, *, sequence: int = 0) -> str:
    """生成单条消息哈希，缺少平台消息 ID 时用顺序兜底。"""

    parts = [
        str(message.sender.value if hasattr(message.sender, "value") else message.sender),
        normalize_message_text(message.raw_text or message.text),
        normalize_message_text(message.time),
        str(sequence),
    ]
    return _sha256("|".join(parts))


def recent_messages_fingerprint(messages: list[ChatMessage], *, window_size: int = 3) -> str:
    """计算最近 N 条有效消息指纹。"""

    window = _effective_messages(messages)[-window_size:]
    if not window:
        return ""
    return _fingerprint_window(window)


def fingerprint_in_messages(
    fingerprint: str,
    messages: list[ChatMessage],
    *,
    max_window_size: int = 3,
) -> bool:
    """判断历史最近消息指纹是否仍可在当前页面消息列表中找到。"""

    return _fingerprint_in_messages(
        fingerprint,
        messages,
        max_window_size=max_window_size,
        legacy_raw_first=False,
    )


def legacy_raw_fingerprint_in_messages(
    fingerprint: str,
    messages: list[ChatMessage],
    *,
    max_window_size: int = 3,
) -> bool:
    """兼容读取历史 raw_text 优先的最近消息指纹。"""

    return _fingerprint_in_messages(
        fingerprint,
        messages,
        max_window_size=max_window_size,
        legacy_raw_first=True,
    )


def _fingerprint_in_messages(
    fingerprint: str,
    messages: list[ChatMessage],
    *,
    max_window_size: int,
    legacy_raw_first: bool,
) -> bool:
    if not fingerprint:
        return False
    effective = _effective_messages(messages)
    fingerprint_window = (
        _legacy_raw_fingerprint_window if legacy_raw_first else _fingerprint_window
    )
    for size in range(1, max_window_size + 1):
        if len(effective) < size:
            continue
        for index in range(0, len(effective) - size + 1):
            if fingerprint_window(effective[index : index + size]) == fingerprint:
                return True
    return False


def _effective_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    return [item for item in messages if normalize_message_text(item.text or item.raw_text)]


def _fingerprint_window(messages: list[ChatMessage]) -> str:
    parts = [normalize_message_text(item.text or item.raw_text) for item in messages]
    return _sha256("\n".join(parts))


def _legacy_raw_fingerprint_window(messages: list[ChatMessage]) -> str:
    parts = [normalize_message_text(item.raw_text or item.text) for item in messages]
    return _sha256("\n".join(parts))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
