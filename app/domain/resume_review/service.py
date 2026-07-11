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
    SHARED_ADMIN_INBOX,
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
        shared_admin_inbox: str = SHARED_ADMIN_INBOX,
    ) -> None:
        self.repository = repository
        self.resume_repository = resume_repository
        self.shared_admin_inbox = shared_admin_inbox

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
        user_name: str = "",
        decision: str,
        reason_tags: list[str] | None = None,
        note: str = "",
        is_admin: bool = False,
    ) -> dict[str, object]:
        """设置合适/不合适/待补充，只保存当前用户的判断。"""

        if decision not in VALID_DECISIONS - {DECISION_UNDECIDED}:
            raise ValueError("invalid_review_decision")
        before = self.repository.get_state(resume_id, user_id)
        assigned_to = before.assigned_to if before and decision == DECISION_SUITABLE else ""
        state = self.repository.upsert_state(
            resume_id=resume_id,
            user_id=user_id,
            user_name=user_name,
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
        completed_assignment = (
            self.repository.complete_shared_assignment(
                resume_id=resume_id,
                shared_inbox_user_id=self.shared_admin_inbox,
                completed_by_user_id=user_id,
                completed_by_user_name=user_name,
            )
            if is_admin
            else None
        )
        return {
            "state": _state_payload(state),
            "assignment": None,
            "completedAssignment": _assignment_payload(completed_assignment)
            if completed_assignment
            else None,
            "eventId": event_id,
        }

    def push_to_admin(
        self,
        *,
        resume_id: str,
        user_id: str,
        user_name: str = "",
        note: str = "",
    ) -> dict[str, object]:
        """把当前用户已标记合适的简历推送到管理员待处理队列。"""

        before = self.repository.get_state(resume_id, user_id)
        if before is None or before.decision != DECISION_SUITABLE:
            raise ValueError("resume_not_suitable_for_push")
        assigned_to = self.shared_admin_inbox
        state = self.repository.upsert_state(
            resume_id=resume_id,
            user_id=user_id,
            user_name=user_name,
            read_status=READ_VIEWED,
            decision=DECISION_SUITABLE,
            reason_tags=before.reason_tags,
            note=note if note else before.note,
            assigned_to=assigned_to,
            viewed_at=(before.viewed_at if before.viewed_at else _now()),
        )
        assignment = self.repository.create_assignment(
            resume_id=resume_id,
            from_user_id=user_id,
            assigned_to_user_id=assigned_to,
            source_decision_id=state.id,
            note=note if note else before.note,
        )
        event_id = self.repository.append_event(
            resume_id=resume_id,
            user_id=user_id,
            event_type="pushed_to_admin",
            before=_state_payload(before),
            after={
                "state": _state_payload(state),
                "assignment": _assignment_payload(assignment),
            },
        )
        return {
            "state": _state_payload(state),
            "assignment": _assignment_payload(assignment),
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
                    f"/api/resumes/{resume.id}/preview-image?page=1" if preview_path else ""
                ),
                "previewPagesUrl": (
                    f"/api/resumes/{resume.id}/preview-pages" if preview_path else ""
                ),
                "downloadUrl": f"/api/resumes/{resume.id}/download" if preview_path else "",
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
            user_name="",
            resume_id=resume_id,
            read_status=READ_UNREAD,
            decision=DECISION_UNDECIDED,
        )

    def states_for_user(self, user_id: str) -> dict[str, ReviewState]:
        """读取用户所有状态。"""

        return self.repository.states_for_user(user_id)

    def reviewer_decisions_for_resumes(
        self,
        resume_ids: list[str],
    ) -> dict[str, list[dict[str, object]]]:
        """Return every non-undecided reviewer decision for visible resumes."""

        grouped = self.repository.states_for_resumes(resume_ids)
        result: dict[str, list[dict[str, object]]] = {}
        for resume_id, states in grouped.items():
            result[resume_id] = [
                _reviewer_decision_payload(state)
                for state in states
                if state.decision != DECISION_UNDECIDED
            ]
        return result

    def member_decisions_for_resumes(
        self,
        resume_ids: list[str],
    ) -> dict[str, list[dict[str, object]]]:
        """Compatibility alias for consumers using the old field name."""

        return self.reviewer_decisions_for_resumes(resume_ids)

    def shared_admin_queue(self) -> list[dict[str, object]]:
        """Return the one pending inbox shared by every administrator."""

        assignments = self.repository.list_assignments(self.shared_admin_inbox)
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
        "userName": state.user_name,
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


def _reviewer_decision_payload(state: ReviewState) -> dict[str, object]:
    payload = _state_payload(state)
    payload["userName"] = state.user_name or _historical_user_name(state.user_id)
    return payload


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
        "completedByUserId": assignment.completed_by_user_id,
        "completedByUserName": assignment.completed_by_user_name,
        "completedAt": assignment.completed_at,
        "createdAt": assignment.created_at,
        "updatedAt": assignment.updated_at,
    }


def _historical_user_name(user_id: str) -> str:
    suffix = str(user_id or "").strip()[-4:] or "未知"
    return f"历史成员（{suffix}）"


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
