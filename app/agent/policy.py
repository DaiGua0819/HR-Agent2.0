"""平台感知策略。

本文件只表达跨平台差异，不承载页面动作。共享 runner 通过这些纯函数决定
是否发送前置话术、是否走 BOSS 常用语入口，避免为每个平台复制一套流程。
"""

from __future__ import annotations

import random

from app.agent.rules import is_ai_basic_rule, resume_request_prompt
from app.core.constants import Platform

OPERATION_RESUME_TYPES = {"运营A", "运营B"}
OPERATION_DIRECT_RESUME_PROMPT_POOL = ("你好可以看看简历吗", "你好，方便发一份简历过来吗")
DIRECT_RESUME_PROMPT_POOL = ("你好，方便发一份简历过来吗", "你好，可以看看简历吗")
ALL_PLATFORM_DIRECT_RESUME_TYPES = {
    "外部财务产品顾问",
    "AI智能体解决方案负责人",
    "投资交易策略研究员",
    "AI产品经理",
}
ALL_PLATFORM_DIRECT_RESUME_ALIASES = {
    "外部财务产品顾问",
    "业财智能化顾问",
    "AI财务场景顾问",
    "财务场景顾问",
    "AI智能体解决方案负责人",
    "AI Solution Architect",
    "AI FDE",
    "AI Workflow Engineer",
    "Workflow Engineer",
    "投资交易策略研究员",
    "投资交易策略研究员（量化与市场情绪方向）",
    "量化与市场情绪方向",
    "AI产品经理",
    "AI 产品经理",
    "AI Product Manager",
    "AI PM",
}


def should_send_prephrase(
    platform: Platform | str,
    position: str,
    rule: dict[str, object] | None,
) -> bool:
    """判断直求简历前是否需要先发文字话术。

    复刻旧 `prepare_direct_resume_request_prompt` 的核心平台门控：
    运营 A/B 三平台都先发运营专用要简历话术；财务 AI 直求简历岗位三平台
    都先发岗位配置的 `resumeRequestPrompt`。
    """

    resume_type = _resume_job_type(position, rule)
    if resume_type in OPERATION_RESUME_TYPES:
        return True
    if resume_type in ALL_PLATFORM_DIRECT_RESUME_ALIASES:
        return bool(prephrase_candidates(platform, position, rule))
    return False


def prephrase_candidates(
    platform: Platform | str,
    position: str,
    rule: dict[str, object] | None,
) -> list[str]:
    """返回直求简历可用话术池。"""

    resume_type = _resume_job_type(position, rule)
    prompts = _rule_prompt_values(rule)
    if resume_type in OPERATION_RESUME_TYPES:
        values = [*OPERATION_DIRECT_RESUME_PROMPT_POOL, *prompts]
        return _dedupe_prompts(values)
    if resume_type in ALL_PLATFORM_DIRECT_RESUME_ALIASES:
        return prompts or list(DIRECT_RESUME_PROMPT_POOL)
    return []


def prephrase_text(
    platform: Platform | str,
    position: str,
    rule: dict[str, object] | None,
) -> str:
    """返回需要发送的直求简历前置话术。"""

    candidates = prephrase_candidates(platform, position, rule)
    if _resume_job_type(position, rule) in OPERATION_RESUME_TYPES:
        return random.choice(OPERATION_DIRECT_RESUME_PROMPT_POOL)
    return random.choice(candidates) if candidates else ""


def should_use_company_info(
    platform: Platform | str,
    position: str,
    rule: dict[str, object] | None,
) -> bool:
    """判断 AI 应用开发基础条件是否走平台扩展动作。"""

    return _platform(platform) == Platform.BOSS and is_ai_basic_rule(position, rule)


def _resume_job_type(position: str, rule: dict[str, object] | None) -> str:
    value = str((rule or {}).get("resumeJobType") or "").strip()
    if value:
        return value
    for item in (*OPERATION_RESUME_TYPES, *ALL_PLATFORM_DIRECT_RESUME_ALIASES):
        if item and item in position:
            return item
    return ""


def _platform(value: Platform | str) -> Platform:
    return value if isinstance(value, Platform) else Platform(str(value).strip().lower())


def _rule_prompt_values(rule: dict[str, object] | None) -> list[str]:
    raw_values = (rule or {}).get("resumeRequestPrompts")
    values: list[str] = []
    if isinstance(raw_values, list):
        values.extend(str(item or "").strip() for item in raw_values)
    prompt = resume_request_prompt(rule)
    if prompt:
        values.append(prompt)
    return _dedupe_prompts(values)


def _dedupe_prompts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in values:
        key = "".join(item.split())
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out
