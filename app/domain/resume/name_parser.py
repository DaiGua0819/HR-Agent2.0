"""Extract a display name from parsed resume text.

This module is intentionally lightweight. It is used after a resume artifact has
already been linked to a platform conversation, so the parsed name is only a
display/search field, not the primary identity key.
"""

from __future__ import annotations

import re
from pathlib import Path

_LABEL_PREFIX_RE = re.compile(r"^(姓\s*名|名字|name)\s*[:：]\s*", re.IGNORECASE)
_LABELED_NAME_RE = re.compile(
    r"(?:姓\s*名|名字|name)\s*[:：]\s*([\u4e00-\u9fffA-Za-z·]{2,16})",
    re.IGNORECASE,
)
_NOISE_RE = re.compile(
    r"(个人信息|基本信息|个人简历|简历|resume|curriculum vitae|cv)",
    re.IGNORECASE,
)


def parse_resume_name(text: str, *, file_name: str = "") -> str:
    """Return the most plausible candidate name, or an empty string."""

    candidate_lines = _candidate_lines(text)
    for line in candidate_lines:
        match = _LABELED_NAME_RE.search(line)
        if match and _looks_like_name(match.group(1)):
            return match.group(1)

    for line in candidate_lines:
        value = _LABEL_PREFIX_RE.sub("", line).strip()
        value = _NOISE_RE.sub("", value).strip(" _-—:：")
        if _looks_like_name(value):
            return value
    stem = Path(file_name).stem if file_name else ""
    stem = _NOISE_RE.sub("", stem).strip(" _-—:：")
    return stem if _looks_like_name(stem) else ""


def _candidate_lines(text: str) -> list[str]:
    lines = []
    for raw in str(text or "").replace("\r", "\n").split("\n"):
        line = " ".join(raw.strip().split())
        if line:
            lines.append(line)
        if len(lines) >= 12:
            break
    return lines


def _looks_like_name(value: str) -> bool:
    if not value:
        return False
    if any(char.isdigit() for char in value):
        return False
    if "@" in value or len(value) > 16:
        return False
    if re.search(r"(电话|手机|本科|硕士|博士|工作|经验|岗位)", value):
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", value))
