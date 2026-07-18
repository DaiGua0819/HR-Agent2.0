"""Interview invite button workflow tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from app.browser.fake_page import FakePage
from app.control_plane.main import create_app
from app.core.constants import Platform
from app.domain.conversation.identity import resolve_or_create_session
from app.domain.conversation.repository import ConversationRepository
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.domain.resume_review.repository import ResumeReviewRepository
from app.domain.resume_review.service import ResumeReviewService
from app.features.interview_invite.service import (
    InterviewInviteError,
    InterviewInviteService,
)
from app.platforms.boss.adapter import BossAdapter
from app.platforms.job51.adapter import Job51Adapter
from app.platforms.types import Candidate, ChatMessage, Conversation, MessageSender
from app.platforms.zhilian.adapter import ZhilianAdapter
from app.worker.runtime import WorkerRuntime
from fastapi.testclient import TestClient


def test_invite_service_dispatches_linked_resume_dry_run(tmp_path: Path) -> None:
    """A hard-linked resume should produce a platform-contact payload and dispatch."""

    resume_repo, conversation_repo, session_id = _linked_resume_fixture(tmp_path)
    dispatcher = RecordingDispatcher({"accepted": True, "readyToExchange": True})
    service = InterviewInviteService(
        resume_repository=resume_repo,
        conversation_repository=conversation_repo,
        dispatcher=dispatcher,
    )

    result = asyncio.run(service.invite("resume-linked", dry_run=True))

    assert result["accepted"] is True
    assert result["dryRun"] is True
    assert result["sourceSessionId"] == session_id
    assert dispatcher.calls[0]["owner"] == "宋峰峰"
    payload = dispatcher.calls[0]["payload"]
    assert payload["platform"] == "boss"
    assert payload["action"] == "exchange_wechat"
    assert payload["platformContact"]["displayName"] == "平台张先生"
    assert payload["platformContact"]["appliedPosition"] == "投资交易策略研究员"
    assert payload["platformContact"]["chatEvidence"][-1]["text"] == "我发简历了"


def test_invite_service_requires_confirmation_for_name_only_match(tmp_path: Path) -> None:
    """Name-only historical matches should not dispatch automatically."""

    database = tmp_path / "invite-name.sqlite"
    resume_repo = ResumeRepository(database)
    conversation_repo = ConversationRepository(database)
    session = resolve_or_create_session(
        conversation_repo,
        _conversation("", "王小丽", "膨润土销售", ["您好", "可以"], platform=Platform.JOB51),
    ).session
    resume_repo.save(
        Resume(
            id="resume-name-only",
            name="王小丽",
            parsed_name="王小丽",
            job_type="膨润土销售",
            payload={"rawText": "王小丽 膨润土销售"},
        )
    )
    dispatcher = RecordingDispatcher({})
    service = InterviewInviteService(
        resume_repository=resume_repo,
        conversation_repository=conversation_repo,
        dispatcher=dispatcher,
    )

    result = asyncio.run(service.invite("resume-name-only", dry_run=True))

    assert result["accepted"] is False
    assert result["requiresConfirmation"] is True
    assert result["reason"] == "missing_linked_session"
    assert result["candidates"][0]["id"] == session.id
    assert dispatcher.calls == []


def test_invite_service_rejects_live_without_confirm(tmp_path: Path) -> None:
    """Live exchange must require the explicit confirmLive guard."""

    resume_repo, conversation_repo, _session_id = _linked_resume_fixture(tmp_path)
    service = InterviewInviteService(
        resume_repository=resume_repo,
        conversation_repository=conversation_repo,
        dispatcher=RecordingDispatcher({}),
    )

    with pytest.raises(InterviewInviteError) as exc:
        asyncio.run(service.invite("resume-linked", dry_run=False, confirm_live=False))

    assert exc.value.reason == "live_confirmation_required"


def test_interview_invite_api_uses_injected_service() -> None:
    """The HTTP route should delegate to the invite service and preserve aliases."""

    app = create_app()
    service = FakeInviteService()
    app.state.interview_invite_service = service

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        response = client.post(
            "/api/interview/invite",
            json={"resumeId": "resume-1", "dryRun": True, "selectedSessionId": "s1"},
        )

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert service.calls == [
        {
            "resume_id": "resume-1",
            "dry_run": True,
            "confirm_live": False,
            "selected_session_id": "s1",
        }
    ]


def test_live_interview_invite_completes_pending_admin_assignment(
    tmp_path: Path,
) -> None:
    """Only an accepted live invite should move the shared task to processed."""

    database = tmp_path / "interview-completion.sqlite"
    resume_repo = ResumeRepository(database)
    resume_repo.save(
        Resume(
            id="resume-1",
            name="候选人甲",
            job_type="AI产品经理",
            payload={"rawText": "候选人甲 AI产品经理"},
        )
    )
    review_service = ResumeReviewService(
        ResumeReviewRepository(database),
        resume_repository=resume_repo,
    )
    review_service.set_decision(
        resume_id="resume-1",
        user_id="feishu:member-a",
        user_name="成员甲",
        decision="suitable",
    )
    review_service.push_to_admin(
        resume_id="resume-1",
        user_id="feishu:member-a",
        user_name="成员甲",
    )
    app = create_app()
    app.state.resume_repository = resume_repo
    app.state.resume_review_service = review_service
    app.state.interview_invite_service = FakeInviteService()
    app.state.auth_session_store_path = tmp_path / "auth.sqlite"

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        preflight = client.post(
            "/api/interview/invite",
            json={"resumeId": "resume-1", "dryRun": True},
        )
        live = client.post(
            "/api/interview/invite",
            json={"resumeId": "resume-1", "dryRun": False, "confirmLive": True},
        )

    assert preflight.status_code == 200
    assert "completedAssignment" not in preflight.json()
    assert live.status_code == 200
    assert live.json()["completedAssignment"]["completionAction"] == "interview_invited"
    assert review_service.shared_admin_queue() == []
    assert len(review_service.shared_admin_queue(status="completed")) == 1


def test_worker_runtime_invite_calls_platform_adapter_dry_run() -> None:
    """Worker invite should use the target platform adapter, not return the old stub."""

    page = _invite_page()
    runtime = WorkerRuntime(
        owner="宋峰峰",
        port=8802,
        cdp_port=9223,
        browser_backend="fake",
    )
    runtime.browser = FakeBrowser({Platform.BOSS: page})
    payload = _invite_payload(dry_run=True)

    result = asyncio.run(runtime.interview_invite(payload))

    assert result["accepted"] is True
    assert result["readyToExchange"] is True
    assert result["dryRun"] is True
    assert page.current_conversation().get("wechat_exchange_clicked") is not True
    assert page.sent_messages == []


@pytest.mark.parametrize(
    ("platform", "adapter_cls"),
    [
        (Platform.BOSS, BossAdapter),
        (Platform.JOB51, Job51Adapter),
        (Platform.ZHILIAN, ZhilianAdapter),
    ],
)
def test_platform_invite_dry_run_locates_exchange_without_side_effect(
    platform: Platform,
    adapter_cls: type[Any],
) -> None:
    """Dry-run should search, verify, and locate WeChat exchange only."""

    page = _invite_page(platform=platform)
    adapter = adapter_cls(page, owner="宋峰峰", dry_run=True)

    result = asyncio.run(adapter.invite_to_interview(_invite_payload(platform, dry_run=True)))

    assert result["accepted"] is True
    assert result["readyToExchange"] is True
    assert result["dryRun"] is True
    assert page.current_conversation().get("wechat_exchange_clicked") is not True
    assert page.sent_messages == []


def test_platform_invite_live_exchanges_wechat_and_sends_followup() -> None:
    """Live invite should click WeChat exchange and then send the fixed follow-up."""

    page = _invite_page(platform=Platform.BOSS)
    adapter = BossAdapter(page, owner="宋峰峰", dry_run=False)

    result = asyncio.run(adapter.invite_to_interview(_invite_payload(dry_run=False)))

    assert result["accepted"] is True
    assert result["exchanged"] is True
    assert page.current_conversation()["wechat_exchange_clicked"] is True
    assert page.sent_messages[-1] == "加我微信沟通"


def test_platform_invite_live_reports_followup_send_failure() -> None:
    """If the follow-up message cannot be verified, the invite is not successful."""

    page = _invite_page(platform=Platform.BOSS, send_fails=True)
    adapter = BossAdapter(page, owner="宋峰峰", dry_run=False)

    result = asyncio.run(adapter.invite_to_interview(_invite_payload(dry_run=False)))

    assert result["accepted"] is False
    assert result["reason"] == "interview_followup_send_failed"
    assert page.current_conversation()["wechat_exchange_clicked"] is True


class RecordingDispatcher:
    """Capture service dispatch payloads."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def interview_invite(self, owner: str, payload: dict[str, Any]) -> Any:
        self.calls.append({"owner": owner, "payload": payload})
        return DispatchLike(owner=owner, platform=Platform(payload["platform"]), result=self.result)


class DispatchLike:
    """Minimal dispatcher result shape used by InterviewInviteService."""

    def __init__(self, owner: str, platform: Platform, result: dict[str, Any]) -> None:
        self.owner = owner
        self.platform = platform
        self.result = result


class FakeInviteService:
    """Route test double."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def invite(
        self,
        resume_id: str,
        *,
        dry_run: bool,
        confirm_live: bool,
        selected_session_id: str = "",
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "resume_id": resume_id,
                "dry_run": dry_run,
                "confirm_live": confirm_live,
                "selected_session_id": selected_session_id,
            }
        )
        return {"accepted": True, "resumeId": resume_id, "dryRun": dry_run}


class FakeBrowser:
    """WorkerRuntime browser test double."""

    def __init__(self, pages: dict[Platform, FakePage]) -> None:
        self.pages = pages
        self.started = False

    async def start(self) -> None:
        self.started = True

    def page_for(self, owner: str, platform: Platform) -> FakePage:
        _ = owner
        return self.pages[platform]

    async def health(self) -> Any:
        return None


def _linked_resume_fixture(tmp_path: Path) -> tuple[ResumeRepository, ConversationRepository, str]:
    database = tmp_path / "invite-linked.sqlite"
    resume_repo = ResumeRepository(database)
    conversation_repo = ConversationRepository(database)
    conversation = _conversation(
        "boss-1",
        "平台张先生",
        "投资交易策略研究员",
        ["您好", "我发简历了"],
        platform=Platform.BOSS,
    )
    session = resolve_or_create_session(conversation_repo, conversation).session
    conversation_repo.upsert_messages(session.id, conversation.messages)
    resume_repo.save(
        Resume(
            id="resume-linked",
            name="解析张三",
            parsed_name="解析张三",
            job_type="投资交易策略研究员",
            linked_session_id=session.id,
            linked_platform=session.platform,
            linked_owner=session.owner,
            linked_platform_conversation_id=session.platform_conversation_id,
            payload={"rawText": "解析张三 投资交易策略研究员"},
        )
    )
    return resume_repo, conversation_repo, session.id


def _conversation(
    conversation_id: str,
    name: str,
    position: str,
    texts: list[str],
    *,
    platform: Platform,
) -> Conversation:
    messages = [
        ChatMessage(
            sender=MessageSender.CANDIDATE if index % 2 else MessageSender.ME,
            text=text,
            raw_text=text,
        )
        for index, text in enumerate(texts)
    ]
    return Conversation(
        id=conversation_id,
        platform=platform,
        owner="宋峰峰",
        candidate=Candidate(name=name, applied_position=position, label=f"{name} {position}"),
        messages=messages,
    )


def _invite_page(platform: Platform = Platform.BOSS, **extra: Any) -> FakePage:
    return FakePage(
        conversations=[
            {
                "id": f"{platform.value}-1",
                "name": "平台张先生",
                "position": "投资交易策略研究员",
                "label": "平台张先生 投资交易策略研究员",
                "latest_message": "我发简历了",
                "unread_count": 0,
                "wechat_exchange_available": True,
                "messages": [{"sender": "other", "text": "我发简历了"}],
                **extra,
            }
        ]
    )


def _invite_payload(platform: Platform = Platform.BOSS, *, dry_run: bool) -> dict[str, Any]:
    return {
        "platform": platform.value,
        "owner": "宋峰峰",
        "sourceSessionId": f"{platform.value}-session",
        "action": "exchange_wechat",
        "dryRun": dry_run,
        "platformContact": {
            "displayName": "平台张先生",
            "label": "平台张先生 投资交易策略研究员",
            "appliedPosition": "投资交易策略研究员",
            "chatEvidence": [{"sender": "other", "text": "我发简历了"}],
        },
    }
