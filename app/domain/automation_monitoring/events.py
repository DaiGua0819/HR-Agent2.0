"""Build normalized contact events from worker conversation results."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from app.domain.automation_monitoring.models import AutomationContactEvent
from app.domain.resume.job_types import canonical_resume_job_type

_ANOMALY_MARKERS = (
    "failed",
    "error",
    "timeout",
    "login_required",
    "security_verification",
    "account_abnormal",
    "download_error",
)


def build_contact_event(
    *,
    owner: str,
    platform: str,
    state: dict[str, object],
    occurred_at: str | None = None,
) -> AutomationContactEvent:
    timestamp = occurred_at or datetime.now(UTC).isoformat()
    action = str(state.get("next_action") or "")
    stage = str(state.get("stage") or "")
    decision = state.get("decision") if isinstance(state.get("decision"), dict) else {}
    decision_action = str(decision.get("action") or action)
    result = decision.get("result") if isinstance(decision.get("result"), dict) else {}
    candidate = state.get("candidate") if isinstance(state.get("candidate"), dict) else {}
    session_id = str(state.get("session_id") or "").strip()
    fingerprint = str(state.get("recent_messages_fingerprint") or "").strip()
    conversation_id = str(state.get("conversation_id") or "").strip()
    contact_key = (
        f"session|{session_id}"
        if session_id
        else f"conversation|{platform}|{owner}|{conversation_id}"
    )
    resume_handling = _resume_handling(
        platform=platform,
        action=action,
        decision_action=decision_action,
        result=result,
    )
    requested_resume = action == "request_resume" or decision_action == "request_resume"
    anomaly_text = " ".join(
        [
            action,
            stage,
            str(decision.get("reason") or ""),
            str(result.get("reason") or ""),
            str(result.get("failureReason") or ""),
            str(result.get("artifactParseStatus") or ""),
        ]
    ).lower()
    anomaly = any(marker in anomaly_text for marker in _ANOMALY_MARKERS)
    event_id = "automation-event-" + hashlib.sha256(
        f"{owner}|{platform}|{contact_key}|{action}|{stage}|{timestamp}".encode()
    ).hexdigest()[:24]
    return AutomationContactEvent(
        id=event_id,
        contactKey=contact_key,
        owner=owner,
        platform=platform,
        candidateName=str(candidate.get("name") or ""),
        jobType=canonical_resume_job_type(
            state.get("applied_position") or candidate.get("applied_position") or ""
        ),
        occurredAt=timestamp,
        action=action or decision_action,
        stage=stage,
        processed=True,
        sentCompanyInfo=(
            action in {"ask", "ask_question", "send_screening_question"}
            or stage in {"screening_question_sent", "basic_conditions_sent"}
        ),
        requestedResume=requested_resume,
        candidateQuestion=bool(state.get("pending_question")) or stage == "unknown_question",
        knowledgeAnswered=action == "answer_question" or stage == "knowledge_hit",
        resumeAcquired=resume_handling in {
            "boss_request_verified_server_imap",
            "local_resume_downloaded",
        },
        resumeHandling=resume_handling,
        resumeFileHash=str(result.get("fileHash") or result.get("file_hash") or ""),
        anomaly=anomaly,
        anomalyReason=(
            str(result.get("failureReason") or result.get("reason") or decision.get("reason") or "")
            if anomaly
            else ""
        ),
        payload={
            "decision": decision,
            "sessionId": session_id,
            "conversationId": conversation_id,
            "recentMessagesFingerprint": fingerprint,
        },
        updatedAt=timestamp,
    )


def _resume_handling(
    *,
    platform: str,
    action: str,
    decision_action: str,
    result: dict[str, Any],
) -> str:
    if platform == "boss":
        reason = str(result.get("reason") or "")
        outcome = str(result.get("outcome") or "")
        verified = bool(result.get("ok")) and (
            action == "request_resume" or decision_action == "request_resume"
        )
        if verified or reason == "boss_attachment_present_no_local_download" or outcome in {
            "request_confirmed",
            "resume_attachment_received",
            "resume_consent_accepted",
        }:
            return "boss_request_verified_server_imap"
    if bool(result.get("downloaded")):
        return "local_resume_downloaded"
    if (
        action == "request_resume" or decision_action == "request_resume"
    ) and bool(result.get("requested") or result.get("confirmed")):
        return "resume_requested_waiting"
    return ""
