"""文本清洗与安全截断工具。

本模块对应旧 `server/utils/text.js` 的无副作用工具：文件名安全片段、文本压缩、
固定长度截断和会话名规整。控制面与领域层共用这些函数，避免在 API 层重复清洗。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_UNSAFE_FILE_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')
_SPACE_RE = re.compile(r"\s+")


def clean_text(value: Any) -> str:
    """把任意值规整成去首尾、合并空白后的文本。"""

    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return _SPACE_RE.sub(" ", text).strip()


def safe_file_part(value: Any, *, fallback: str = "unknown") -> str:
    """生成可放入文件名的安全片段，保持旧工具“非法字符替换为下划线”的语义。"""

    cleaned = clean_text(value)
    if not cleaned:
        return fallback
    safe = _UNSAFE_FILE_CHARS.sub("_", cleaned)
    safe = re.sub(r"_+", "_", safe).strip("._ ")
    return safe or fallback


def compact_safe_file_part(value: Any, *, max_length: int = 48, fallback: str = "unknown") -> str:
    """生成更短的文件名片段，用于批量导入和下载记忆 key。"""

    return clip_text(safe_file_part(value, fallback=fallback), max_length=max_length)


def clip_text(value: Any, *, max_length: int = 2000, suffix: str = "...") -> str:
    """安全截断文本；长度未超限时原样返回。"""

    text = clean_text(value)
    if max_length <= 0 or len(text) <= max_length:
        return text
    keep = max(0, max_length - len(suffix))
    return text[:keep].rstrip() + suffix


def normalize_conversation_name(value: Any) -> str:
    """规整会话名，移除常见平台状态标签。"""

    text = clean_text(value)
    for token in ("[送达]", "[已读]", "[平台推荐]", "【送达】", "【已读】"):
        text = text.replace(token, "")
    return clean_text(text)


def contains_any(text: str, keywords: list[str]) -> list[str]:
    """返回在文本中出现过的关键词，供 JD 匹配和来源识别复用。"""

    haystack = clean_text(text).lower()
    return [keyword for keyword in keywords if keyword and keyword.lower() in haystack]
