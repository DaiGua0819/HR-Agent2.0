"""飞书多维表字段与资产定义。

对应旧 `bitableAssets.js` 的职责：集中维护表名、字段名和字段映射，避免编排服务硬编码。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InterviewBitableTables:
    """面试中心使用的多维表。"""

    candidates: str = "interview_candidates"
    sessions: str = "interview_sessions"
    feedback: str = "interview_feedback"


class CandidateFields:
    """候选人表字段名。"""

    NAME = "候选人"
    PHONE = "手机号"
    POSITION = "应聘岗位"
    RESUME_ID = "简历ID"
    MATCH_SCORE = "匹配分"
    RESUME_IMAGE = "简历图片"


class SessionFields:
    """面试会话表字段名。"""

    SESSION_ID = "会话ID"
    RESUME_ID = "简历ID"
    CANDIDATE = "候选人"
    POSITION = "面试岗位"
    QUESTIONS = "面试题"
    STATUS = "状态"
    SUMMARY_IMAGE = "面试小结图"


class FeedbackFields:
    """反馈回填字段名。"""

    SESSION_ID = "会话ID"
    RESULT = "面试结果"
    FEEDBACK = "反馈"
    INTERVIEWER = "面试官"


BITABLE_TABLES = InterviewBitableTables()
