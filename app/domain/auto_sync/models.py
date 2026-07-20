"""Wire models for encrypted automatic synchronization batches."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.automation_monitoring.models import (
    AutomationContactEvent,
    AutomationRuntimeStatus,
)


class SyncModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class SyncFile(SyncModel):
    sha256: str
    filename: str
    media_type: str = Field(alias="mediaType")
    content_base64: str = Field(alias="contentBase64")


class SyncResume(SyncModel):
    id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    phone_key: str | None = Field(default=None, alias="phoneKey")
    job_type: str | None = Field(default=None, alias="jobType")
    match_score: int | None = Field(default=None, alias="matchScore")
    updated_at: str = Field(alias="updatedAt")
    parsed_name: str = Field(default="", alias="parsedName")
    linked_session_id: str = Field(default="", alias="linkedSessionId")
    linked_platform: str = Field(default="", alias="linkedPlatform")
    linked_owner: str = Field(default="", alias="linkedOwner")
    linked_platform_conversation_id: str = Field(
        default="",
        alias="linkedPlatformConversationId",
    )
    source_artifact_id: str = Field(default="", alias="sourceArtifactId")
    file: SyncFile | None = None


class SyncSession(SyncModel):
    id: str
    platform: str
    owner: str
    candidate_name: str = Field(default="", alias="candidateName")
    position: str = ""
    applied_position: str = Field(default="", alias="appliedPosition")
    platform_conversation_id: str = Field(default="", alias="platformConversationId")
    label: str = ""
    current_stage: str = Field(default="", alias="currentStage")
    next_action: str = Field(default="", alias="nextAction")
    recent_messages_fingerprint: str = Field(
        default="",
        alias="recentMessagesFingerprint",
    )
    identity_confidence: str = Field(default="", alias="identityConfidence")
    identity_warnings: str = Field(default="[]", alias="identityWarnings")
    last_seen_at: str = Field(alias="lastSeenAt")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class SyncMessage(SyncModel):
    id: str
    session_id: str = Field(alias="sessionId")
    sender: str
    text: str
    raw_text: str = Field(default="", alias="rawText")
    sent_at: str = Field(default="", alias="sentAt")
    platform_message_id: str = Field(default="", alias="platformMessageId")
    message_hash: str = Field(alias="messageHash")
    created_at: str = Field(alias="createdAt")


class SyncBatch(SyncModel):
    batch_id: str = Field(alias="batchId")
    source: str
    created_at: str = Field(alias="createdAt")
    resumes: list[SyncResume] = Field(default_factory=list)
    sessions: list[SyncSession] = Field(default_factory=list)
    messages: list[SyncMessage] = Field(default_factory=list)
    operation_events: list[AutomationContactEvent] = Field(
        default_factory=list,
        alias="operationEvents",
    )
    runtime_statuses: list[AutomationRuntimeStatus] = Field(
        default_factory=list,
        alias="runtimeStatuses",
    )
