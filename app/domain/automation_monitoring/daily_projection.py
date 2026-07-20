"""Build idempotent per-candidate daily monitoring projections."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from app.domain.automation_monitoring.models import AutomationContactEvent
from app.domain.resume.job_types import canonical_resume_job_type

CHINA_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

_SENT_COMPANY_ACTIONS = {
    "ask",
    "ask_basic_conditions",
    "ask_question",
    "ask_screening",
    "send_screening_question",
}
_SENT_COMPANY_STAGES = {"basic_conditions_sent", "screening_question_sent"}
_QUESTION_ACTIONS = {"answer_question", "escalate"}
_QUESTION_STAGES = {"knowledge_hit", "silent_question", "unknown_question"}
_ANOMALY_MARKERS = (
    "blocked",
    "error",
    "failed",
    "login_required",
    "security_verification",
    "timeout",
)
_ANOMALY_STAGES = {"unconfigured_position"}


@dataclass(frozen=True)
class DailyProjectionExport:
    events: list[AutomationContactEvent]
    coverage: dict[str, int]
    summary: dict[str, object]


@dataclass
class _Projection:
    day: date
    identity: str
    contact_key: str
    owner: str
    platform: str
    candidate_name: str = ""
    job_type: str = ""
    session_id: str = ""
    conversation_id: str = ""
    latest_at: datetime | None = None
    latest_priority: int = -1
    action: str = ""
    stage: str = ""
    processed: bool = False
    sent_company_info: bool = False
    requested_resume: bool = False
    candidate_question: bool = False
    knowledge_answered: bool = False
    resume_acquired: bool = False
    resume_handling: str = ""
    resume_file_hash: str = ""
    anomaly: bool = False
    anomaly_reasons: list[str] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)

    def update_latest(
        self,
        *,
        occurred_at: datetime,
        priority: int,
        action: str,
        stage: str,
        candidate_name: str = "",
        job_type: str = "",
        owner: str = "",
        platform: str = "",
        conversation_id: str = "",
    ) -> None:
        rank = (occurred_at, priority)
        current_rank = (self.latest_at or datetime.min.replace(tzinfo=UTC), self.latest_priority)
        if rank < current_rank:
            return
        self.latest_at = occurred_at
        self.latest_priority = priority
        self.action = action or self.action
        self.stage = stage or self.stage
        self.candidate_name = candidate_name or self.candidate_name
        self.job_type = job_type or self.job_type
        self.owner = owner or self.owner
        self.platform = platform or self.platform
        self.conversation_id = conversation_id or self.conversation_id

    def add_anomaly_reasons(self, reasons: list[str]) -> None:
        for reason in reasons:
            normalized = str(reason or "").strip()
            if normalized and normalized not in self.anomaly_reasons:
                self.anomaly_reasons.append(normalized)

    def to_event(self) -> AutomationContactEvent:
        occurred_at = self.latest_at or datetime.combine(
            self.day, time.min, CHINA_TZ
        ).astimezone(UTC)
        day_text = self.day.isoformat()
        identity_hash = hashlib.sha256(self.identity.encode("utf-8")).hexdigest()[:24]
        return AutomationContactEvent(
            id=f"automation-daily-{day_text}-{identity_hash}",
            contactKey=self.contact_key,
            owner=self.owner,
            platform=self.platform,
            candidateName=self.candidate_name,
            jobType=canonical_resume_job_type(self.job_type),
            occurredAt=occurred_at.isoformat(),
            action=self.action,
            stage=self.stage,
            processed=self.processed,
            sentCompanyInfo=self.sent_company_info,
            requestedResume=self.requested_resume,
            candidateQuestion=self.candidate_question,
            knowledgeAnswered=self.knowledge_answered,
            resumeAcquired=self.resume_acquired,
            resumeHandling=self.resume_handling,
            resumeFileHash=self.resume_file_hash,
            anomaly=self.anomaly,
            anomalyReason="; ".join(self.anomaly_reasons),
            payload={
                "source": "daily_projection",
                "date": day_text,
                "sessionId": self.session_id,
                "conversationId": self.conversation_id,
                "sources": sorted(self.sources),
            },
            updatedAt=occurred_at.isoformat(),
        )


def build_daily_projections(
    *,
    database_path: str | Path,
    run_dir: str | Path,
    start_date: date,
    end_date: date,
) -> DailyProjectionExport:
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    database = Path(database_path)
    sessions = _load_sessions(database)
    sessions_by_conversation = {
        (
            str(session.get("platform") or ""),
            str(session.get("owner") or ""),
            str(session.get("platform_conversation_id") or ""),
        ): session_id
        for session_id, session in sessions.items()
        if session.get("platform_conversation_id")
    }
    projections: dict[tuple[date, str], _Projection] = {}
    exact_keys: set[tuple[date, str]] = set()
    fallback_keys: set[tuple[date, str]] = set()
    unresolved_records = 0
    manager_results = 0

    for record in _iter_manager_results(Path(run_dir)):
        occurred_at = _parse_datetime(record.get("timestamp"))
        if occurred_at is None:
            unresolved_records += 1
            continue
        day = occurred_at.astimezone(CHINA_TZ).date()
        if day < start_date or day > end_date:
            continue
        manager_results += 1
        summary = _object(record.get("summary"))
        response = _object(record.get("response"))
        session_id = _first_text(
            summary.get("canonicalSessionId"),
            summary.get("canonical_session_id"),
            response.get("canonicalSessionId"),
            response.get("canonical_session_id"),
        )
        owner = _first_text(record.get("owner"), response.get("owner"))
        platform = _first_text(record.get("platform"), response.get("platform"))
        conversation_id = _first_text(
            summary.get("conversationId"),
            response.get("conversationId"),
            summary.get("selectedConversationId"),
            response.get("selectedConversationId"),
        )
        if not session_id:
            session_id = sessions_by_conversation.get(
                (platform, owner, conversation_id), ""
            )
        session = sessions.get(session_id, {}) if session_id else {}
        candidate = _object(response.get("candidate"))
        candidate_name = _first_text(candidate.get("name"), session.get("candidate_name"))
        job_type = _first_text(
            response.get("appliedPosition"),
            response.get("applied_position"),
            session.get("applied_position"),
            session.get("position"),
        )
        identity = _stable_identity(
            session_id=session_id,
            platform=platform,
            owner=owner,
            conversation_id=conversation_id,
            candidate_name=candidate_name,
            job_type=job_type,
        )
        if not identity:
            unresolved_records += 1
            continue
        key = (day, identity)
        projection = projections.setdefault(
            key,
            _new_projection(
                day=day,
                identity=identity,
                session_id=session_id,
                platform=platform,
                owner=owner,
                conversation_id=conversation_id,
                session=session,
                candidate_name=candidate_name,
                job_type=job_type,
            ),
        )
        if session_id:
            exact_keys.add(key)
        else:
            fallback_keys.add(key)
        action = _first_text(
            summary.get("nextAction"),
            summary.get("next_action"),
            response.get("nextAction"),
            response.get("next_action"),
            _object(response.get("decision")).get("action"),
        )
        stage = _first_text(summary.get("stage"), response.get("stage"))
        projection.update_latest(
            occurred_at=occurred_at,
            priority=2,
            action=action,
            stage=stage,
            candidate_name=candidate_name,
            job_type=job_type,
            owner=owner,
            platform=platform,
            conversation_id=conversation_id,
        )
        projection.sources.add("manager")
        _merge_action_flags(projection, action=action, stage=stage)
        projection.processed = projection.processed or bool(
            summary.get("processed") or response.get("processed")
        )
        resume_handling = _first_text(
            summary.get("resumeHandling"),
            summary.get("resume_handling"),
            response.get("resumeHandling"),
            response.get("resume_handling"),
        )
        decision_result = _object(_object(response.get("decision")).get("result"))
        _merge_resume_result(
            projection,
            platform=platform,
            action=action,
            resume_handling=resume_handling,
            result=decision_result,
        )
        classification = _object(record.get("classification"))
        reasons = [str(item) for item in classification.get("reasons", []) if str(item)]
        _merge_anomaly_flags(
            projection,
            action=action,
            stage=stage,
            reasons=reasons,
            explicit=bool(classification.get("is_anomaly")),
        )

    for session in sessions.values():
        occurred_at = _parse_datetime(session.get("updated_at"))
        if occurred_at is None:
            continue
        day = occurred_at.astimezone(CHINA_TZ).date()
        if day < start_date or day > end_date:
            continue
        session_id = str(session.get("id") or "")
        identity = _stable_identity(
            session_id=session_id,
            platform=str(session.get("platform") or ""),
            owner=str(session.get("owner") or ""),
            conversation_id=str(session.get("platform_conversation_id") or ""),
        )
        if not identity:
            continue
        key = (day, identity)
        created = key not in projections
        projection = projections.setdefault(
            key,
            _new_projection(
                day=day,
                identity=identity,
                session_id=session_id,
                platform=str(session.get("platform") or ""),
                owner=str(session.get("owner") or ""),
                conversation_id=str(session.get("platform_conversation_id") or ""),
                session=session,
                candidate_name=str(session.get("candidate_name") or ""),
                job_type=_first_text(session.get("applied_position"), session.get("position")),
            ),
        )
        action = str(session.get("next_action") or "")
        stage = str(session.get("current_stage") or "")
        projection.update_latest(
            occurred_at=occurred_at,
            priority=1,
            action=action,
            stage=stage,
            candidate_name=str(session.get("candidate_name") or ""),
            job_type=_first_text(session.get("applied_position"), session.get("position")),
            owner=str(session.get("owner") or ""),
            platform=str(session.get("platform") or ""),
            conversation_id=str(session.get("platform_conversation_id") or ""),
        )
        projection.processed = True
        projection.sources.add("session")
        _merge_action_flags(projection, action=action, stage=stage)
        _merge_anomaly_flags(projection, action=action, stage=stage)
        if created:
            fallback_keys.add(key)

    _merge_resume_artifacts(
        database=database,
        sessions=sessions,
        projections=projections,
        fallback_keys=fallback_keys,
        start_date=start_date,
        end_date=end_date,
    )
    events = sorted(
        (projection.to_event() for projection in projections.values()),
        key=lambda item: (item.occurred_at, item.id),
    )
    coverage = {
        "managerContactResults": manager_results,
        "exactCandidates": len(exact_keys),
        "fallbackCandidates": len(fallback_keys),
        "unresolvedRecords": unresolved_records,
        "events": len(events),
    }
    return DailyProjectionExport(
        events=events,
        coverage=coverage,
        summary=_summary(events),
    )


def _load_sessions(database: Path) -> dict[str, dict[str, object]]:
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM conversation_sessions").fetchall()
    return {str(row["id"]): dict(row) for row in rows}


def _iter_manager_results(run_dir: Path):
    if not run_dir.exists():
        return
    for path in sorted(run_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and item.get("event") == "contact_result":
                yield item


def _merge_resume_artifacts(
    *,
    database: Path,
    sessions: dict[str, dict[str, object]],
    projections: dict[tuple[date, str], _Projection],
    fallback_keys: set[tuple[date, str]],
    start_date: date,
    end_date: date,
) -> None:
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM resume_artifacts").fetchall()
    for row in rows:
        artifact = dict(row)
        occurred_at = _parse_datetime(artifact.get("created_at"))
        if occurred_at is None:
            continue
        day = occurred_at.astimezone(CHINA_TZ).date()
        if day < start_date or day > end_date:
            continue
        session_id = str(artifact.get("session_id") or "")
        session = sessions.get(session_id, {})
        identity = _stable_identity(
            session_id=session_id,
            platform=str(artifact.get("platform") or ""),
            owner=str(artifact.get("owner") or ""),
            conversation_id=str(artifact.get("platform_conversation_id") or ""),
            candidate_name=_first_text(
                artifact.get("candidate_name_from_platform"), session.get("candidate_name")
            ),
            job_type=_first_text(artifact.get("position"), session.get("applied_position")),
        )
        if not identity:
            continue
        key = (day, identity)
        created = key not in projections
        projection = projections.setdefault(
            key,
            _new_projection(
                day=day,
                identity=identity,
                session_id=session_id,
                platform=str(artifact.get("platform") or ""),
                owner=str(artifact.get("owner") or ""),
                conversation_id=str(artifact.get("platform_conversation_id") or ""),
                session=session,
                candidate_name=_first_text(
                    artifact.get("candidate_name_from_platform"), session.get("candidate_name")
                ),
                job_type=_first_text(
                    artifact.get("position"), session.get("applied_position")
                ),
            ),
        )
        projection.update_latest(
            occurred_at=occurred_at,
            priority=0,
            action="request_resume",
            stage="resume_attachment_downloaded",
            candidate_name=_first_text(
                artifact.get("candidate_name_from_platform"), session.get("candidate_name")
            ),
            job_type=_first_text(artifact.get("position"), session.get("applied_position")),
            owner=str(artifact.get("owner") or ""),
            platform=str(artifact.get("platform") or ""),
            conversation_id=str(artifact.get("platform_conversation_id") or ""),
        )
        projection.processed = True
        projection.requested_resume = True
        projection.resume_acquired = True
        projection.resume_handling = "local_resume_downloaded"
        projection.resume_file_hash = str(artifact.get("file_hash") or projection.resume_file_hash)
        projection.sources.add("resume_artifact")
        if created:
            fallback_keys.add(key)


def _new_projection(
    *,
    day: date,
    identity: str,
    session_id: str,
    platform: str,
    owner: str,
    conversation_id: str,
    session: dict[str, object],
    candidate_name: str = "",
    job_type: str = "",
) -> _Projection:
    return _Projection(
        day=day,
        identity=identity,
        contact_key=(
            f"session|{session_id}"
            if session_id
            else (
                f"conversation|{platform}|{owner}|{conversation_id}"
                if conversation_id
                else f"candidate|{platform}|{owner}|{candidate_name}|{job_type}"
            )
        ),
        owner=owner or str(session.get("owner") or ""),
        platform=platform or str(session.get("platform") or ""),
        candidate_name=candidate_name or str(session.get("candidate_name") or ""),
        job_type=job_type
        or _first_text(session.get("applied_position"), session.get("position")),
        session_id=session_id,
        conversation_id=conversation_id,
    )


def _stable_identity(
    *,
    session_id: str,
    platform: str,
    owner: str,
    conversation_id: str,
    candidate_name: str = "",
    job_type: str = "",
) -> str:
    if session_id:
        return f"session|{session_id}"
    if platform and owner and conversation_id:
        return f"conversation|{platform}|{owner}|{conversation_id}"
    if platform and owner and candidate_name and job_type:
        return f"candidate|{platform}|{owner}|{candidate_name}|{job_type}"
    return ""


def _merge_action_flags(projection: _Projection, *, action: str, stage: str) -> None:
    projection.sent_company_info = projection.sent_company_info or (
        action in _SENT_COMPANY_ACTIONS or stage in _SENT_COMPANY_STAGES
    )
    projection.requested_resume = projection.requested_resume or action in {
        "request_resume",
        "request_resume_failed",
    }
    projection.candidate_question = projection.candidate_question or (
        action in _QUESTION_ACTIONS or stage in _QUESTION_STAGES
    )
    projection.knowledge_answered = projection.knowledge_answered or (
        action == "answer_question" or stage == "knowledge_hit"
    )


def _merge_anomaly_flags(
    projection: _Projection,
    *,
    action: str,
    stage: str,
    reasons: list[str] | None = None,
    explicit: bool = False,
) -> None:
    normalized_reasons = reasons or []
    anomaly_text = " ".join([action, stage, *normalized_reasons]).lower()
    if not explicit and stage not in _ANOMALY_STAGES and not any(
        marker in anomaly_text for marker in _ANOMALY_MARKERS
    ):
        return
    projection.anomaly = True
    projection.add_anomaly_reasons(normalized_reasons or [stage or action])


def _merge_resume_result(
    projection: _Projection,
    *,
    platform: str,
    action: str,
    resume_handling: str,
    result: dict[str, object],
) -> None:
    if resume_handling:
        if projection.resume_handling != "local_resume_downloaded":
            projection.resume_handling = resume_handling
    if resume_handling in {"boss_request_verified_server_imap", "local_resume_downloaded"}:
        projection.resume_acquired = True
    if bool(result.get("downloaded")):
        projection.resume_acquired = True
        projection.resume_handling = "local_resume_downloaded"
    if platform == "boss" and action == "request_resume" and bool(result.get("ok")):
        projection.resume_acquired = True
        projection.resume_handling = "boss_request_verified_server_imap"
    projection.resume_file_hash = _first_text(
        result.get("fileHash"), result.get("file_hash"), projection.resume_file_hash
    )


def _summary(events: list[AutomationContactEvent]) -> dict[str, object]:
    by_date: dict[str, dict[str, int]] = {}
    resume_keys_by_date: dict[str, set[str]] = {}
    for event in events:
        day = event.payload.get("date") or event.occurred_at[:10]
        counts = by_date.setdefault(
            str(day),
            {
                "processedContacts": 0,
                "sentCompanyInfo": 0,
                "requestedResume": 0,
                "candidateQuestions": 0,
                "knowledgeAnswered": 0,
                "businessResumeAcquisitions": 0,
                "anomalies": 0,
            },
        )
        resume_keys = resume_keys_by_date.setdefault(str(day), set())
        counts["processedContacts"] += int(event.processed)
        counts["sentCompanyInfo"] += int(event.sent_company_info)
        counts["requestedResume"] += int(event.requested_resume)
        counts["candidateQuestions"] += int(event.candidate_question)
        counts["knowledgeAnswered"] += int(event.knowledge_answered)
        if event.resume_acquired:
            resume_key = (
                event.contact_key
                if event.platform == "boss"
                else event.resume_file_hash
            )
            if resume_key and resume_key not in resume_keys:
                resume_keys.add(resume_key)
                counts["businessResumeAcquisitions"] += 1
        counts["anomalies"] += int(event.anomaly)
    return {"byDate": by_date, "totalEvents": len(events)}


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
