"""简历审阅用例编排。"""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.resume.files import preview_file_path
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.domain.resume_review.models import (
    DECISION_SUITABLE,
    DECISION_UNDECIDED,
    READ_UNREAD,
    READ_VIEWED,
    VALID_DECISIONS,
    ReviewAssignment,
    ReviewState,
)
from app.domain.resume_review.repository import ResumeReviewRepository


class ResumeReviewService:
    """处理已看、审核结论和合适队列。"""

    def __init__(
        self,
        repository: ResumeReviewRepository,
        *,
        resume_repository: ResumeRepository,
        default_assignee: str = "local-admin",
    ) -> None:
        self.repository = repository
        self.resume_repository = resume_repository
        self.default_assignee = default_assignee

    def mark_viewed(self, resume_id: str, user_id: str) -> ReviewState:
        """打开简历时标记当前用户已看。"""

        before = self.repository.get_state(resume_id, user_id)
        viewed_at = before.viewed_at if before and before.viewed_at else _now()
        state = self.repository.upsert_state(
            resume_id=resume_id,
            user_id=user_id,
            read_status=READ_VIEWED,
            viewed_at=viewed_at,
        )
        self.repository.append_event(
            resume_id=resume_id,
            user_id=user_id,
            event_type="viewed",
            before=_state_payload(before),
            after=_state_payload(state),
        )
        return state

    def set_decision(
        self,
        *,
        resume_id: str,
        user_id: str,
        decision: str,
        reason_tags: list[str] | None = None,
        note: str = "",
        assign_to: str = "",
    ) -> dict[str, object]:
        """设置合适/不合适/待补充。合适会创建待处理任务。"""

        if decision not in VALID_DECISIONS - {DECISION_UNDECIDED}:
            raise ValueError("invalid_review_decision")
        before = self.repository.get_state(resume_id, user_id)
        assigned_to = assign_to or (self.default_assignee if decision == DECISION_SUITABLE else "")
        state = self.repository.upsert_state(
            resume_id=resume_id,
            user_id=user_id,
            read_status=READ_VIEWED,
            decision=decision,
            reason_tags=reason_tags or [],
            note=note,
            assigned_to=assigned_to,
            viewed_at=(before.viewed_at if before and before.viewed_at else _now()),
        )
        event_id = self.repository.append_event(
            resume_id=resume_id,
            user_id=user_id,
            event_type="decision_changed",
            before=_state_payload(before),
            after=_state_payload(state),
        )
        assignment = None
        if decision == DECISION_SUITABLE:
            assignment = self.repository.create_assignment(
                resume_id=resume_id,
                from_user_id=user_id,
                assigned_to_user_id=assigned_to,
                source_decision_id=state.id,
                note=note,
            )
            self.repository.append_event(
                resume_id=resume_id,
                user_id=user_id,
                event_type="assigned",
                before={},
                after=_assignment_payload(assignment),
            )
        return {
            "state": _state_payload(state),
            "assignment": _assignment_payload(assignment) if assignment else None,
            "eventId": event_id,
        }

    def context_for_resume(
        self,
        *,
        resume: Resume,
        user_id: str,
        mark_viewed: bool = True,
    ) -> dict[str, object]:
        """返回审阅工作台需要的一份简历上下文。"""

        if mark_viewed:
            state = self.mark_viewed(resume.id, user_id)
        else:
            state = self.state_for_resume(resume.id, user_id)
        file_path = (
            resume.payload.get("file_path")
            or resume.payload.get("filePath")
            or resume.payload.get("pdfPath")
            or ""
        )
        preview_path = preview_file_path(resume)
        parse_status = resume.payload.get("parse_status") or resume.payload.get("parseStatus") or ""
        return {
            "resume": resume.model_dump(),
            "reviewState": _state_payload(state),
            "score": {
                "value": resume.match_score,
                "grade": _score_grade(resume.match_score),
            },
            "conversation": {
                "sessionId": resume.linked_session_id,
                "platform": resume.linked_platform or resume.source_platform,
                "owner": resume.linked_owner or resume.source_owner,
                "platformConversationId": resume.linked_platform_conversation_id,
                "messages": [],
            },
            "artifact": {
                "sourceArtifactId": resume.source_artifact_id,
                "filePath": str(file_path),
                "parseStatus": str(parse_status),
            },
            "file": {
                "available": preview_path is not None,
                "previewUrl": f"/api/resumes/{resume.id}/file" if preview_path else "",
                "previewImageUrl": (
                    f"/api/resumes/{resume.id}/preview-image" if preview_path else ""
                ),
                "name": preview_path.name if preview_path else "",
            },
            "permissions": {
                "canReview": True,
                "canAssign": True,
                "canRescore": True,
            },
        }

    def state_for_resume(self, resume_id: str, user_id: str) -> ReviewState:
        """读取状态，未存在时返回未看/未判断的虚拟状态。"""

        return self.repository.get_state(resume_id, user_id) or ReviewState(
            id="",
            user_id=user_id,
            resume_id=resume_id,
            read_status=READ_UNREAD,
            decision=DECISION_UNDECIDED,
        )

    def states_for_user(self, user_id: str) -> dict[str, ReviewState]:
        """读取用户所有状态。"""

        return self.repository.states_for_user(user_id)

    def queue_for_user(self, user_id: str) -> list[dict[str, object]]:
        """返回待我处理队列。"""

        assignments = self.repository.list_assignments(user_id)
        result: list[dict[str, object]] = []
        for assignment in assignments:
            record = self.resume_repository.get(assignment.resume_id)
            result.append(
                {
                    "assignment": _assignment_payload(assignment),
                    "resume": Resume.from_record(record).model_dump() if record else None,
                }
            )
        return result


def _state_payload(state: ReviewState | None) -> dict[str, object]:
    if state is None:
        return {}
    return {
        "id": state.id,
        "userId": state.user_id,
        "resumeId": state.resume_id,
        "readStatus": state.read_status,
        "decision": state.decision,
        "reasonTags": state.reason_tags,
        "note": state.note,
        "assignedTo": state.assigned_to,
        "viewedAt": state.viewed_at,
        "createdAt": state.created_at,
        "updatedAt": state.updated_at,
    }


def _assignment_payload(assignment: ReviewAssignment | None) -> dict[str, object]:
    if assignment is None:
        return {}
    return {
        "id": assignment.id,
        "resumeId": assignment.resume_id,
        "fromUserId": assignment.from_user_id,
        "assignedToUserId": assignment.assigned_to_user_id,
        "status": assignment.status,
        "sourceDecisionId": assignment.source_decision_id,
        "note": assignment.note,
        "createdAt": assignment.created_at,
        "updatedAt": assignment.updated_at,
    }


def _score_grade(score: int | None) -> str:
    if score is None:
        return ""
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def _now() -> str:
    return datetime.now(UTC).isoformat()
