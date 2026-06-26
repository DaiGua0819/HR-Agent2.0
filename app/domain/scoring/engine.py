"""打分引擎。

移植旧评分版本常量、JD v5 分档和会话/自动化匹配打分入口。所有函数都是纯逻辑，
写回由 service/repository 负责。
"""

from __future__ import annotations

from typing import Any

from app.core.text import clean_text
from app.domain.scoring.jd_match import calculate_jd_match, extract_resume_text

AI_V4_SCORING_VERSION = "v4-agent-depth-human-feedback"
AI_V4_SCORING_VERSION_NAME = "历史评分 v4"
AI_V4_SCORING_VERSION_DESCRIPTION = (
    "Agent项目深度评分：项目经历 65 分，技术栈 35 分，支持人工反馈补充规则。"
)
POSITION_SCORING_VERSION = "v5-position-must-bonus"
POSITION_SCORING_VERSION_NAME = "岗位评分 v5"
POSITION_SCORING_VERSION_DESCRIPTION = (
    "岗位评分规则改为必须项、加分项和风险项，不再依赖岗位描述标签匹配。"
)
SCORING_VERSION = AI_V4_SCORING_VERSION
SCORING_VERSION_NAME = AI_V4_SCORING_VERSION_NAME
SCORING_VERSION_DESCRIPTION = AI_V4_SCORING_VERSION_DESCRIPTION


def score_resume_for_profile(
    payload: dict[str, Any],
    job_type: str | None = None,
) -> dict[str, Any]:
    """对单份简历执行 JD v5 匹配。"""

    text = extract_resume_text(payload)
    selected_job = job_type or payload.get("job_type") or payload.get("applied_position")
    return calculate_jd_match(text, str(selected_job or ""))


def score_resume_conversation_match(
    resume_payload: dict[str, Any],
    conversation: dict[str, Any],
) -> dict[str, Any]:
    """简历与会话匹配评分，保留旧逻辑的姓名/岗位/消息证据加权思路。"""

    resume_text = extract_resume_text(resume_payload)
    convo_text = clean_text(" ".join(str(value) for value in conversation.values()))
    name = clean_text(resume_payload.get("name") or resume_payload.get("candidateName"))
    job = clean_text(resume_payload.get("job_type") or resume_payload.get("applied_position"))

    score = 0
    evidence: list[str] = []
    if name and name in convo_text:
        score += 40
        evidence.append("name_exact")
    if job and job in convo_text:
        score += 30
        evidence.append("job_type")
    if resume_text and any(token in convo_text for token in ("简历", "附件", "投递")):
        score += 15
        evidence.append("resume_message")
    if clean_text(conversation.get("updated_at") or conversation.get("time")):
        score += 15
        evidence.append("time_signal")
    return {"score": min(100, score), "evidence": evidence}


def score_automation_contact_match(
    candidate_text: str,
    job_type: str,
) -> dict[str, Any]:
    """主动联系候选人与岗位的自动化匹配评分。"""

    return calculate_jd_match(candidate_text, job_type)
