"""ConversationRunner persistence hooks for sessions, status, and artifacts."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from app.agent.state import GraphState
from app.domain.conversation.dedup import recent_messages_fingerprint
from app.domain.conversation.identity import resolve_or_create_session
from app.domain.conversation.models import CandidateStatus, SessionResolution
from app.domain.conversation.repository import ConversationRepository
from app.domain.resume.artifacts import ResumeArtifactStore, parse_artifact
from app.domain.resume.repository import ResumeRepository
from app.platforms.types import Conversation
from app.settings import AppSettings, load_settings


class ConversationPersistence:
    """Keep persistence out of the platform-neutral business runner."""

    def __init__(
        self,
        *,
        repository: ConversationRepository | None,
        artifact_store: ResumeArtifactStore | None,
        adapter: object,
    ) -> None:
        self.repository = repository
        self.artifact_store = artifact_store
        self.resume_repository = (
            ResumeRepository.for_initialized_database(artifact_store.database_path)
            if artifact_store is not None
            else None
        )
        self.adapter = adapter
        self.session_resolution: SessionResolution | None = None
        self.candidate_status: CandidateStatus | None = None
        self.recent_messages_fingerprint = ""
        self.resume_artifact_issue: dict[str, str] = {}

    def attach(self, state: GraphState, conversation: Conversation) -> None:
        """Resolve the platform session and persist observed messages."""

        if self.repository is None:
            return
        resolution = resolve_or_create_session(self.repository, conversation)
        self.session_resolution = resolution
        identity_conflict = "recent_messages_not_matched" in resolution.warnings
        if identity_conflict:
            fingerprint = recent_messages_fingerprint(conversation.messages)
        else:
            self.repository.upsert_messages(resolution.session.id, conversation.messages)
            fingerprint = self.repository.update_recent_fingerprint(
                resolution.session.id,
                conversation.messages,
            )
        status = self.repository.get_status(resolution.session.id)
        self.candidate_status = status
        self.recent_messages_fingerprint = fingerprint
        state["session_id"] = resolution.session.id
        state["identity_confidence"] = resolution.confidence
        state["identity_warnings"] = resolution.warnings
        state["recent_messages_fingerprint"] = fingerprint
        state["candidate_status"] = asdict(status)

    def should_skip_current_message_snapshot(self) -> bool:
        """Check the canonical session/message key before any business action."""

        if self.repository is None or self.session_resolution is None:
            return False
        session = self.session_resolution.session
        return self.repository.should_skip_processing_snapshot(
            owner=session.owner,
            platform=session.platform,
            canonical_session_id=session.id,
            latest_message_fingerprint=self.recent_messages_fingerprint,
        )

    def has_resume_completion(self) -> bool:
        """Return whether a real resume action has already been persisted."""

        return self.has_resume_downloaded()

    def has_resume_downloaded(self) -> bool:
        """Return whether a real resume file has already been persisted."""

        status = self.candidate_status
        if self.artifact_store is None or self.session_resolution is None:
            return bool(status and status.resume_downloaded)
        session = self.session_resolution.session
        artifact = self.artifact_store.find_business_download(
            session_id=session.id,
            platform=session.platform,
            owner=session.owner,
            platform_conversation_id=session.platform_conversation_id,
            position=session.position,
        )
        if artifact is None:
            if status and status.resume_downloaded and session.platform in {"job51", "zhilian"}:
                self.resume_artifact_issue = _resume_artifact_issue(
                    "downloaded_status_without_artifact"
                )
                return False
            return bool(status and status.resume_downloaded)
        if artifact.parse_status == "parsed":
            self.resume_artifact_issue = {}
            return True
        if self.resume_repository is None:
            return False
        try:
            parsed = parse_artifact(
                self.artifact_store,
                self.resume_repository,
                artifact,
            )
        except Exception as error:
            self.resume_artifact_issue = _resume_artifact_issue(str(error), artifact.id)
            return False
        if parsed.parse_status != "parsed":
            self.resume_artifact_issue = _resume_artifact_issue(
                parsed.error or "artifact_not_parsed",
                parsed.id,
            )
            return False
        self.resume_artifact_issue = {}
        return True

    def has_resume_request_pending(self) -> bool:
        """Return whether a prior real resume request is waiting for the candidate."""

        status = self.candidate_status
        return bool(status and status.resume_requested and not status.resume_downloaded)

    def finish(
        self,
        state: GraphState,
        *,
        action: str,
        reason: str,
        extra: dict[str, Any],
    ) -> None:
        """Persist the runner outcome after the business decision is made."""

        if self.repository is None or self.session_resolution is None:
            return
        session = self.session_resolution.session
        self.repository.update_session_progress(
            session.id,
            current_stage=reason,
            next_action=action,
        )
        status = self.candidate_status or self.repository.get_status(session.id)
        status = self._next_status(status, action=action, reason=reason, extra=extra)
        self.candidate_status = self.repository.save_status(status)
        state["candidate_status"] = asdict(self.candidate_status)

    def _next_status(
        self,
        status: CandidateStatus,
        *,
        action: str,
        reason: str,
        extra: dict[str, Any],
    ) -> CandidateStatus:
        dry_run = bool(getattr(self.adapter, "dry_run", False))
        asked_questions = list(status.asked_questions)
        next_question = status.next_question
        if action == "ask_screening":
            reply = str(extra.get("reply") or "")
            next_question = reply
            if reply and not dry_run and reply not in asked_questions:
                asked_questions.append(reply)

        result = extra.get("result") if isinstance(extra.get("result"), dict) else {}
        resume_requested = status.resume_requested
        resume_received = status.resume_received
        resume_downloaded = status.resume_downloaded
        resume_path = status.resume_path
        if result.get("resumeReceived") and not dry_run:
            resume_received = True
        if action == "request_resume" and not dry_run:
            resume_requested = resume_requested or bool(
                result.get("requested") or result.get("confirmed")
            )
            downloaded_now = bool(
                result.get("downloaded") and result.get("filePath")
            )
            resume_path = str(result.get("filePath") or resume_path)
            artifact_persisted = self._record_resume_artifact(result) if downloaded_now else False
            resume_downloaded = resume_downloaded or (downloaded_now and artifact_persisted)

        if self.resume_artifact_issue:
            for key, value in self.resume_artifact_issue.items():
                result.setdefault(key, value)

        payload = dict(status.payload)
        payload["lastDecision"] = {"action": action, "reason": reason}
        return replace(
            status,
            asked_questions=asked_questions,
            resume_requested=resume_requested,
            resume_received=resume_received,
            resume_downloaded=resume_downloaded,
            resume_path=resume_path,
            last_action=action,
            next_question=next_question,
            decided_result=reason,
            payload=payload,
        )

    def _record_resume_artifact(self, result: dict[str, Any]) -> bool:
        if (
            self.artifact_store is None
            or self.resume_repository is None
            or self.session_resolution is None
        ):
            return False
        file_path = str(result.get("filePath") or "")
        file_hash = str(result.get("fileHash") or "")
        if not file_path or not file_hash:
            return False
        session = self.session_resolution.session
        position = str(result.get("resumeJobType") or session.position).strip()
        artifact = None
        try:
            artifact = self.artifact_store.record_download(
                session_id=session.id,
                platform=session.platform,
                owner=session.owner,
                platform_conversation_id=session.platform_conversation_id,
                candidate_name_from_platform=session.candidate_name,
                position=position,
                file_path=file_path,
                file_hash=file_hash,
                source_kind=str(result.get("sourceKind") or result.get("source") or "download"),
            )
            parsed = parse_artifact(
                self.artifact_store,
                self.resume_repository,
                artifact,
            )
        except Exception as error:
            self.resume_artifact_issue = _resume_artifact_issue(str(error))
            result.update(self.resume_artifact_issue)
            return artifact is not None
        result["artifactId"] = parsed.id
        result["artifactParseStatus"] = parsed.parse_status
        if parsed.resume_id:
            result["resumeId"] = parsed.resume_id
        if parsed.parse_status != "parsed":
            self.resume_artifact_issue = _resume_artifact_issue(
                parsed.error or "artifact_not_parsed",
                parsed.id,
            )
            result.update(self.resume_artifact_issue)
            return True
        self.resume_artifact_issue = {}
        return True


def build_persistence_from_settings(
    settings: AppSettings | None = None,
) -> tuple[ConversationRepository, ResumeArtifactStore]:
    """Build the default SQLite persistence pair for runtime entrypoints."""

    resolved = settings or load_settings()
    database_path = resolved.resolved_database_path
    return ConversationRepository(database_path), ResumeArtifactStore(database_path)


def _resume_artifact_issue(error: str, artifact_id: str = "") -> dict[str, str]:
    issue = {
        "artifactParseStatus": "failed",
        "artifactParseError": str(error or "artifact_not_parsed"),
        "failureReason": "resume_artifact_parse_failed",
    }
    if artifact_id:
        issue["artifactId"] = artifact_id
    return issue
