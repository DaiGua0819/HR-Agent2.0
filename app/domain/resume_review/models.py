"""简历审阅状态模型。

该模块只描述“谁看过、谁判断、分配给谁”，不承载简历正文和评分逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field

READ_UNREAD = "unread"
READ_VIEWED = "viewed"

DECISION_UNDECIDED = "undecided"
DECISION_SUITABLE = "suitable"
DECISION_UNSUITABLE = "unsuitable"
DECISION_NEEDS_MORE_INFO = "needs_more_info"

VALID_DECISIONS = {
    DECISION_UNDECIDED,
    DECISION_SUITABLE,
    DECISION_UNSUITABLE,
    DECISION_NEEDS_MORE_INFO,
}

SHARED_ADMIN_INBOX = "shared-admin-inbox"


@dataclass(frozen=True)
class ReviewState:
    """单个用户对单份简历的审阅状态。"""

    id: str
    user_id: str
    user_name: str
    resume_id: str
    read_status: str = READ_UNREAD
    decision: str = DECISION_UNDECIDED
    reason_tags: list[str] = field(default_factory=list)
    note: str = ""
    assigned_to: str = ""
    viewed_at: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class ReviewAssignment:
    """合适简历进入负责人处理队列后的任务。"""

    id: str
    resume_id: str
    from_user_id: str
    assigned_to_user_id: str
    status: str
    source_decision_id: str = ""
    note: str = ""
    completed_by_user_id: str = ""
    completed_by_user_name: str = ""
    completed_at: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class LocalUser:
    """本地开发阶段的当前用户模型，后续可替换为飞书登录用户。"""

    id: str
    name: str
    roles: list[str]
    permissions: list[str]
    owners: list[str]
    platforms: list[str]
