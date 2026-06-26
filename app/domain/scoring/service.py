"""打分服务编排。

服务层把简历模型、JD 匹配引擎、规则读取和建议内存桩串起来；它不负责真实数据库写入。
"""

from __future__ import annotations

from typing import Any

from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.domain.scoring.engine import (
    POSITION_SCORING_VERSION,
    score_resume_for_profile,
)
from app.domain.scoring.rules import list_scoring_rules, load_scoring_rules
from app.domain.scoring.suggestions import (
    GLOBAL_RULE_SUGGESTIONS,
    suggest_rule_adjustment,
    suggestion_to_dict,
)


class ScoringService:
    """评分用例服务。"""

    def __init__(self, repository: ResumeRepository | None = None) -> None:
        self.repository = repository

    def score_resume(self, resume: Resume) -> dict[str, Any]:
        """给定简历模型，返回分数、等级和证据。"""

        job_type = resume.job_type or resume.applied_position
        result = score_resume_for_profile(resume.payload, job_type)
        return {
            "resumeId": resume.id,
            "score": result["score"],
            "level": result["level"],
            "jobType": job_type,
            "version": POSITION_SCORING_VERSION,
            "evidence": {
                "must": result["must"]["items"],
                "bonus": result["bonus"]["items"],
                "risks": result["risks"]["items"],
            },
            "raw": result,
        }

    def score_resume_id(self, resume_id: str) -> dict[str, Any] | None:
        """按 id 读取简历并评分。"""

        if self.repository is None:
            return None
        record = self.repository.get(resume_id)
        if record is None:
            return None
        return self.score_resume(Resume.from_record(record))

    def rules(self, job_type: str | None = None) -> dict[str, Any]:
        """读取评分规则。"""

        return load_scoring_rules(job_type) if job_type else list_scoring_rules()

    def submit_feedback(self, resume_id: str, feedback: str) -> dict[str, Any]:
        """提交反馈并生成内存规则建议。"""

        return suggest_rule_adjustment(resume_id, feedback)

    def list_suggestions(self, *, status: str | None = None) -> list[dict[str, Any]]:
        """列出规则建议。"""

        return [
            suggestion_to_dict(item)
            for item in GLOBAL_RULE_SUGGESTIONS.list(status=status)
        ]

    def resolve_suggestion(self, suggestion_id: str, status: str) -> dict[str, Any] | None:
        """采纳或拒绝一条建议。"""

        item = GLOBAL_RULE_SUGGESTIONS.set_status(suggestion_id, status)
        return suggestion_to_dict(item) if item else None


def build_scoring_service(repository: ResumeRepository | None = None) -> ScoringService:
    """装配评分服务。"""

    return ScoringService(repository)


def re_score_resume(resume_id: str) -> dict[str, Any]:
    """兼容旧 stub 的函数入口。"""

    service = build_scoring_service(ResumeRepository.from_settings())
    result = service.score_resume_id(resume_id)
    if result is None:
        return {"resumeId": resume_id, "status": "not_found"}
    return result
