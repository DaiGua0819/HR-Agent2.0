"""Resume job type normalization and display helpers."""

from __future__ import annotations

from collections.abc import Iterable

from app.core.text import clean_text

OPERATION_A = "运营A"
OPERATION_B = "运营B"
INVESTMENT_TRADING = "投资交易策略研究员（量化与市场情绪方向）"
INVESTMENT_TRADING_DISPLAY = "投资策略研究"
AI_PRODUCT_MANAGER = "AI产品经理"


def canonical_resume_job_type(value: object) -> str:
    """Return the legacy resume-library job name for known aliases."""

    text = clean_text(value)
    compact = text.replace(" ", "").lower()
    if not compact:
        return ""
    if (
        "运营a" in compact
        or "企业内容运营负责人" in text
        or ("b2b" in compact and "短视频" in text)
        or ("内容运营负责人" in text and "短视频" in text)
    ):
        return OPERATION_A
    if (
        "运营b" in compact
        or "b端社交媒体运营" in compact
        or "社交媒体运营" in text
        or ("b端" in compact and "运营" in text)
    ):
        return OPERATION_B
    if (
        "投资策略研究" in text
        or "投资交易策略研究员" in text
        or "交易策略研究员" in text
        or "量化交易策略研究员" in text
        or "量化策略研究员" in text
        or "市场情绪研究员" in text
        or "量化与市场情绪方向" in text
    ):
        return INVESTMENT_TRADING
    if (
        "ai产品经理" in compact
        or "aiproductmanager" in compact
        or "aipm" in compact
        or "ai product manager" in text.lower()
        or "ai pm" in text.lower()
    ):
        return AI_PRODUCT_MANAGER
    return text


def display_resume_job_type(value: object) -> str:
    """Return the job name that should be shown in the resume library."""

    canonical = canonical_resume_job_type(value)
    if canonical == INVESTMENT_TRADING:
        return INVESTMENT_TRADING_DISPLAY
    return canonical


def job_type_matches_scope(job_type: object, allowed_job_type: object) -> bool:
    """Match a stored job name against an allowed canonical job or alias."""

    allowed = clean_text(allowed_job_type)
    if allowed == "*":
        return True
    job = clean_text(job_type)
    if not job or not allowed:
        return False
    canonical_job = canonical_resume_job_type(job)
    canonical_allowed = canonical_resume_job_type(allowed)
    return (
        allowed == job
        or allowed == canonical_job
        or canonical_allowed == job
        or canonical_allowed == canonical_job
        or allowed in job
        or job in allowed
    )


def any_job_type_matches(job_type: object, allowed_job_types: Iterable[object]) -> bool:
    """Return whether a job matches any configured allowed job."""

    return any(job_type_matches_scope(job_type, allowed) for allowed in allowed_job_types)
