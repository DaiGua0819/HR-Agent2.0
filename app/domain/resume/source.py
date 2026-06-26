"""简历来源识别与规整。

对应旧 `resumeSource.js` 的职责：从平台、账号、文件名、payload 元数据中推断统一来源，
供简历库筛选和监控聚合使用。
"""

from __future__ import annotations

from typing import Any

from app.core.constants import Platform
from app.core.text import clean_text, contains_any

_PLATFORM_ALIASES = {
    Platform.BOSS.value: ["boss", "boss直聘", "直聘"],
    Platform.JOB51.value: ["51job", "前程无忧", "51"],
    Platform.ZHILIAN.value: ["zhilian", "智联", "智联招聘"],
}


def normalize_source_platform(value: Any) -> str | None:
    """把来源平台规整为 `boss` / `job51` / `zhilian`。"""

    text = clean_text(value).lower()
    if not text:
        return None
    for platform, aliases in _PLATFORM_ALIASES.items():
        if contains_any(text, aliases):
            return platform
    return None


def infer_resume_source(payload: dict[str, Any], *, fallback: str = "unknown") -> dict[str, str]:
    """从 payload 中推断来源平台、账号和原始来源文本。"""

    source_text = clean_text(
        payload.get("source")
        or payload.get("resumeSource")
        or payload.get("platform")
        or payload.get("fileName")
        or payload.get("rawText")
    )
    platform = normalize_source_platform(source_text) or fallback
    owner = clean_text(payload.get("owner") or payload.get("account") or payload.get("operator"))
    return {
        "platform": platform,
        "owner": owner,
        "raw": source_text,
    }
