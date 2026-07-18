from pathlib import Path

from app.control_plane.main import create_app
from app.domain.conversation.models import ConversationSession
from app.domain.conversation.repository import ConversationRepository
from app.domain.conversation.service import MAX_CONVERSATION_MESSAGES, ResumeConversationService
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.domain.resume.service import ResumeService
from app.platforms.types import ChatMessage, MessageSender
from fastapi.testclient import TestClient


def _session(session_id: str = "session-1") -> ConversationSession:
    return ConversationSession(
        id=session_id,
        platform="boss",
        owner="owner",
        candidate_name="Li Le",
        position="AI developer intern",
        updated_at="2026-07-13T12:43:26+00:00",
    )


def _linked_resume(session_id: str = "session-1") -> Resume:
    return Resume(
        id="resume-1",
        name="Li Le",
        parsed_name="Li Le",
        job_type="AI developer intern",
        linked_session_id=session_id,
        linked_platform="boss",
        linked_owner="owner",
    )


def test_linked_resume_returns_chronological_read_only_messages(tmp_path: Path) -> None:
    repository = ConversationRepository(tmp_path / "conversation.sqlite")
    repository.save_session(_session())
    repository.upsert_messages(
        "session-1",
        [
            ChatMessage(
                sender=MessageSender.CANDIDATE,
                text="What are the work hours?",
                time="20:31",
            ),
            ChatMessage(
                sender=MessageSender.ME,
                text="The work hours are 9:00-18:00",
                time="20:32",
            ),
            ChatMessage(
                sender=MessageSender.SYSTEM,
                text="The other party sent you a resume",
                time="20:35",
            ),
        ],
    )

    payload = ResumeConversationService(repository).get_for_resume(_linked_resume())

    assert payload["matched"] is True
    assert payload["matchMode"] == "linked_session_id"
    assert payload["conversation"]["platform"] == "boss"
    assert payload["conversation"]["owner"] == "owner"
    assert [item["sender"] for item in payload["messages"]] == ["other", "me", "system"]
    assert [item["text"] for item in payload["messages"]] == [
        "What are the work hours?",
        "The work hours are 9:00-18:00",
        "The other party sent you a resume",
    ]


def test_broken_or_ambiguous_resume_link_never_returns_messages(tmp_path: Path) -> None:
    repository = ConversationRepository(tmp_path / "conversation.sqlite")
    repository.save_session(_session("candidate-a"))
    repository.save_session(_session("candidate-b"))
    service = ResumeConversationService(repository)

    broken = service.get_for_resume(_linked_resume("missing-session"))
    unlinked = service.get_for_resume(
        Resume(id="resume-2", name="Li Le", parsed_name="Li Le", job_type="AI developer intern")
    )

    assert broken["matched"] is False
    assert broken["reason"] == "conversation_not_linked"
    assert broken["messages"] == []
    assert unlinked["matched"] is False
    assert unlinked["reason"] == "conversation_ambiguous"
    assert unlinked["messages"] == []


def test_unlinked_resume_uses_unique_identity_session_with_messages(tmp_path: Path) -> None:
    repository = ConversationRepository(tmp_path / "conversation.sqlite")
    repository.save_session(_session())
    repository.upsert_messages(
        "session-1",
        [ChatMessage(sender=MessageSender.CANDIDATE, text="hello")],
    )

    payload = ResumeConversationService(repository).get_for_resume(
        Resume(
            id="resume-2",
            name="Li Le",
            parsed_name="Li Le",
            job_type="AI developer intern",
            linked_platform="boss",
            linked_owner="owner",
        )
    )

    assert payload["matched"] is True
    assert payload["matchMode"] == "unique_identity_fallback"
    assert payload["conversation"]["sessionId"] == "session-1"
    assert payload["messages"][0]["text"] == "hello"


def test_unique_identity_fallback_accepts_canonical_job_alias(tmp_path: Path) -> None:
    repository = ConversationRepository(tmp_path / "conversation.sqlite")
    repository.save_session(
        ConversationSession(
            id="session-ai-pm",
            platform="boss",
            owner="owner",
            candidate_name="Candidate",
            position="AI产品经理",
        )
    )
    repository.upsert_messages(
        "session-ai-pm",
        [ChatMessage(sender=MessageSender.CANDIDATE, text="resume sent")],
    )

    payload = ResumeConversationService(repository).get_for_resume(
        Resume(
            id="resume-ai-pm",
            parsed_name="Candidate",
            job_type="AI PM",
            linked_platform="boss",
            linked_owner="owner",
        )
    )

    assert payload["matched"] is True
    assert payload["conversation"]["sessionId"] == "session-ai-pm"


def test_unique_identity_fallback_respects_owner_and_requires_messages(tmp_path: Path) -> None:
    repository = ConversationRepository(tmp_path / "conversation.sqlite")
    repository.save_session(_session("owner-a-session"))
    repository.save_session(
        ConversationSession(
            **{
                **_session("owner-b-session").__dict__,
                "owner": "other-owner",
            }
        )
    )
    repository.upsert_messages(
        "owner-b-session",
        [ChatMessage(sender=MessageSender.CANDIDATE, text="wrong owner")],
    )

    payload = ResumeConversationService(repository).get_for_resume(
        Resume(
            id="resume-owner-a",
            parsed_name="Li Le",
            job_type="AI developer intern",
            linked_platform="boss",
            linked_owner="owner",
        )
    )

    assert payload["matched"] is False
    assert payload["reason"] == "conversation_not_linked"
    assert payload["messages"] == []


def test_conversation_history_is_limited_to_latest_200_messages(tmp_path: Path) -> None:
    repository = ConversationRepository(tmp_path / "conversation.sqlite")
    repository.save_session(_session())
    repository.upsert_messages(
        "session-1",
        [
            ChatMessage(sender=MessageSender.CANDIDATE, text=f"message-{index:03d}")
            for index in range(MAX_CONVERSATION_MESSAGES + 5)
        ],
    )

    payload = ResumeConversationService(repository).get_for_resume(_linked_resume())

    assert payload["conversation"]["messageCount"] == 205
    assert payload["conversation"]["truncated"] is True
    assert len(payload["messages"]) == MAX_CONVERSATION_MESSAGES
    assert payload["messages"][0]["text"] == "message-005"
    assert payload["messages"][-1]["text"] == "message-204"


def _conversation_app(tmp_path: Path):
    conversation_repository = ConversationRepository(tmp_path / "conversation.sqlite")
    conversation_repository.save_session(_session())
    conversation_repository.upsert_messages(
        "session-1",
        [ChatMessage(sender=MessageSender.CANDIDATE, text="hello", time="20:31")],
    )
    resume_repository = ResumeRepository.in_memory([_linked_resume().to_record()])
    app = create_app()
    app.state.auth_session_store_path = tmp_path / "auth.sqlite"
    app.state.resume_repository = resume_repository
    app.state.resume_service = ResumeService(resume_repository)
    app.state.resume_conversation_service = ResumeConversationService(conversation_repository)
    return app


def test_admin_can_read_linked_resume_conversation(tmp_path: Path) -> None:
    app = _conversation_app(tmp_path)

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        response = client.get("/api/resumes/resume-1/conversation")

    assert response.status_code == 200
    assert response.json()["matched"] is True
    assert response.json()["messages"][0]["text"] == "hello"


def test_member_cannot_read_resume_conversation(tmp_path: Path) -> None:
    app = _conversation_app(tmp_path)

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "member", "password": "member"})
        response = client.get("/api/resumes/resume-1/conversation")

    assert response.status_code == 403
    assert response.json()["detail"] == "admin_conversation_forbidden"


def test_missing_resume_returns_not_found_after_admin_check(tmp_path: Path) -> None:
    app = _conversation_app(tmp_path)

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        response = client.get("/api/resumes/missing/conversation")

    assert response.status_code == 404
    assert response.json()["detail"] == "resume_not_found"
