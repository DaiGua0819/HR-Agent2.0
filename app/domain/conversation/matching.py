"""High-confidence matching between imported resumes and chat sessions."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.conversation.models import ConversationSession
from app.domain.conversation.repository import ConversationRepository
from app.domain.resume.job_types import canonical_resume_job_type


@dataclass(frozen=True)
class ConversationMatch:
    session: ConversationSession | None
    match_mode: str
    reason: str
    candidate_count: int


def resolve_unique_conversation(
    repository: ConversationRepository,
    *,
    candidate_name: str,
    position: str,
    platform: str = "",
    owner: str = "",
) -> ConversationMatch:
    """Return one message-bearing session only when identity evidence is unique."""

    name = candidate_name.strip()
    canonical_position = canonical_resume_job_type(position)
    normalized_platform = platform.strip()
    if normalized_platform.lower() == "unknown":
        normalized_platform = ""
    if not name or not canonical_position:
        return ConversationMatch(None, "none", "conversation_not_linked", 0)

    candidates = repository.find_resume_link_candidates(
        candidate_name=name,
        platform=normalized_platform,
        owner=owner,
    )
    position_matches = [
        session
        for session in candidates
        if canonical_resume_job_type(session.position) == canonical_position
    ]
    if len(position_matches) > 1:
        return ConversationMatch(
            None,
            "none",
            "conversation_ambiguous",
            len(position_matches),
        )
    if not position_matches:
        return ConversationMatch(None, "none", "conversation_not_linked", 0)

    session = position_matches[0]
    if repository.count_messages(session.id) < 1:
        return ConversationMatch(None, "none", "conversation_not_linked", 1)
    return ConversationMatch(session, "unique_identity_fallback", "", 1)
