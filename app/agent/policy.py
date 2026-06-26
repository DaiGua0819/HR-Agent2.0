"""平台感知策略。

本文件只表达跨平台差异，不承载页面动作。共享 runner 通过这些纯函数决定
是否发送前置话术、是否走 BOSS 常用语入口，避免为每个平台复制一套流程。
"""

from __future__ import annotations

from app.agent.rules import is_ai_basic_rule, resume_request_prompt
from app.core.constants import Platform

BOSS_OPERATION_PREPHRASE = "可以发一份简历过来吗"
OPERATION_RESUME_TYPES = {"运营A", "运营B"}
ALL_PLATFORM_DIRECT_RESUME_TYPES = {"外部财务产品顾问", "AI智能体解决方案负责人"}
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
}


def should_send_prephrase(
    platform: Platform | str,
    position: str,
    rule: dict[str, object] | None,
) -> bool:
    """判断直求简历前是否需要先发文字话术。

    复刻旧 `prepare_direct_resume_request_prompt` 的核心平台门控：
    BOSS 运营 A/B 先发固定话术；51job/智联运营 A/B 不发；财务 AI 直求
    简历岗位三平台都先发岗位配置的 `resumeRequestPrompt`。
    """

    resume_type = _resume_job_type(position, rule)
    if resume_type in ALL_PLATFORM_DIRECT_RESUME_ALIASES:
        return bool(resume_request_prompt(rule))
    return _platform(platform) == Platform.BOSS and resume_type in OPERATION_RESUME_TYPES


def prephrase_text(
    platform: Platform | str,
    position: str,
    rule: dict[str, object] | None,
) -> str:
    """返回需要发送的直求简历前置话术。"""

    if not should_send_prephrase(platform, position, rule):
        return ""
    prompt = resume_request_prompt(rule)
    if prompt:
        return prompt
    if _resume_job_type(position, rule) in OPERATION_RESUME_TYPES:
        return BOSS_OPERATION_PREPHRASE
    return ""


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
