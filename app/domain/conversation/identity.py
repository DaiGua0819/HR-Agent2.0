"""候选人会话身份定位。"""

from __future__ import annotations

import hashlib

from app.domain.conversation.dedup import (
    fingerprint_in_messages,
    legacy_raw_fingerprint_in_messages,
    recent_messages_fingerprint,
)
from app.domain.conversation.models import ConversationSession, SessionResolution
from app.domain.conversation.repository import ConversationRepository
from app.platforms.types import Conversation


def resolve_or_create_session(
    repository: ConversationRepository,
    conversation: Conversation,
) -> SessionResolution:
    """定位或创建候选人会话 session。"""

    platform = conversation.platform.value
    owner = conversation.owner
    platform_conversation_id = _stable_platform_conversation_id(conversation.id)
    candidate_name = conversation.candidate.name.strip()
    position = conversation.candidate.applied_position.strip()
    fingerprint = recent_messages_fingerprint(conversation.messages)
    warnings: list[str] = []

    existing = repository.find_by_platform_identity(
        platform=platform,
        owner=owner,
        platform_conversation_id=platform_conversation_id,
        position=position,
    )
    if existing is not None:
        preserve_trusted_identity = False
        fingerprint_matches = bool(existing.recent_messages_fingerprint) and (
            verify_identity_by_recent_messages(
                existing.recent_messages_fingerprint,
                conversation,
            )
        )
        if not fingerprint_matches and not _candidate_names_match(
            existing.candidate_name,
            candidate_name,
        ):
            warnings.append("recent_messages_not_matched")
            preserve_trusted_identity = True
        session = _updated_session(
            existing,
            conversation,
            fingerprint=fingerprint,
            confidence="platform_id_position",
            warnings=warnings,
            preserve_trusted_identity=preserve_trusted_identity,
        )
        return SessionResolution(repository.save_session(session), "platform_id_position", warnings)

    if not platform_conversation_id:
        for candidate in repository.find_candidate_sessions(
            platform=platform,
            owner=owner,
            candidate_name=candidate_name,
            position=position,
        ):
            matched_recent_messages = verify_identity_by_recent_messages(
                candidate.recent_messages_fingerprint,
                conversation,
            ) or legacy_raw_fingerprint_in_messages(
                candidate.recent_messages_fingerprint,
                conversation.messages,
            )
            if matched_recent_messages:
                session = _updated_session(
                    candidate,
                    conversation,
                    fingerprint=fingerprint,
                    confidence="recent_messages",
                    warnings=[],
                )
                return SessionResolution(repository.save_session(session), "recent_messages", [])
        warnings.append("fallback_created_without_platform_conversation_id")

    session = ConversationSession(
        id=_session_id(
            platform=platform,
            owner=owner,
            platform_conversation_id=platform_conversation_id,
            candidate_name=candidate_name,
            position=position,
            fingerprint=fingerprint,
        ),
        platform=platform,
        owner=owner,
        candidate_name=candidate_name,
        position=position,
        applied_position=position,
        platform_conversation_id=platform_conversation_id,
        label=conversation.candidate.label,
        recent_messages_fingerprint=fingerprint,
        identity_confidence="new",
        identity_warnings=warnings,
    )
    return SessionResolution(repository.save_session(session), "new", warnings)


def verify_identity_by_recent_messages(
    stored_fingerprint: str,
    conversation: Conversation,
) -> bool:
    """用历史最近消息指纹在当前页面消息列表中做辅助确认。"""

    return fingerprint_in_messages(stored_fingerprint, conversation.messages)


def _candidate_names_match(stored: str, current: str) -> bool:
    stored_normalized = "".join(stored.split()).casefold()
    current_normalized = "".join(current.split()).casefold()
    return bool(
        stored_normalized
        and current_normalized
        and stored_normalized == current_normalized
    )


def _updated_session(
    session: ConversationSession,
    conversation: Conversation,
    *,
    fingerprint: str,
    confidence: str,
    warnings: list[str],
    preserve_trusted_identity: bool = False,
) -> ConversationSession:
    return ConversationSession(
        id=session.id,
        platform=session.platform,
        owner=session.owner,
        candidate_name=(
            session.candidate_name
            if preserve_trusted_identity
            else conversation.candidate.name.strip() or session.candidate_name
        ),
        position=conversation.candidate.applied_position.strip() or session.position,
        applied_position=(
            conversation.candidate.applied_position.strip()
            or session.applied_position
        ),
        platform_conversation_id=(
            _stable_platform_conversation_id(conversation.id)
            or session.platform_conversation_id
        ),
        label=(
            session.label
            if preserve_trusted_identity
            else conversation.candidate.label or session.label
        ),
        current_stage=session.current_stage,
        next_action=session.next_action,
        recent_messages_fingerprint=(
            session.recent_messages_fingerprint
            if preserve_trusted_identity
            else fingerprint or session.recent_messages_fingerprint
        ),
        identity_confidence=confidence,
        identity_warnings=warnings,
        last_seen_at=session.last_seen_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _session_id(
    *,
    platform: str,
    owner: str,
    platform_conversation_id: str,
    candidate_name: str,
    position: str,
    fingerprint: str,
) -> str:
    identity = platform_conversation_id or f"{candidate_name}|{fingerprint}"
    digest = hashlib.sha256(
        "|".join([platform, owner, identity, position]).encode("utf-8")
    ).hexdigest()
    return f"conv_{digest[:24]}"


def _stable_platform_conversation_id(value: object) -> str:
    raw = str(value or "").strip()
    compact = "".join(raw.split())
    if compact in {"[已读]", "[未读]", "已读", "未读", "不合适"}:
        return ""
    if compact.startswith("[") and compact.endswith("]") and len(compact) <= 8:
        return ""
    return raw
