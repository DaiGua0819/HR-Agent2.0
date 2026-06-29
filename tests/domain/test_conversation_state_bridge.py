"""候选人会话状态与简历 artifact 桥接测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agent.runner import ConversationRunner
from app.browser.fake_page import FakePage
from app.core.constants import Platform
from app.db.engine import connect, run_migrations
from app.domain.conversation.identity import resolve_or_create_session
from app.domain.conversation.models import CandidateStatus
from app.domain.conversation.repository import ConversationRepository
from app.domain.resume.artifacts import ResumeArtifactStore, parse_pending_artifacts
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.features.interview_center.service import InterviewCenterService
from app.platforms.boss.adapter import BossAdapter
from app.platforms.job51.adapter import Job51Adapter
from app.platforms.types import Candidate, ChatMessage, Conversation, MessageSender


def test_migration_adds_conversation_and_resume_bridge_tables(tmp_path: Path) -> None:
    """迁移幂等创建会话状态表、artifact 表和简历桥接字段。"""

    database = tmp_path / "bridge.sqlite"
    run_migrations(database)
    run_migrations(database)

    with connect(database) as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        resume_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(resumes)").fetchall()
        }

    assert {
        "conversation_sessions",
        "conversation_messages",
        "candidate_status",
        "resume_artifacts",
    } <= tables
    assert {
        "parsed_name",
        "linked_session_id",
        "linked_platform",
        "linked_owner",
        "linked_platform_conversation_id",
        "source_artifact_id",
    } <= resume_columns


def test_identity_includes_position_and_recent_message_fallback(tmp_path: Path) -> None:
    """同平台 ID 不同岗位不串档；缺 ID 时可用最近消息指纹复用 session。"""

    repository = ConversationRepository(tmp_path / "identity.sqlite")
    first = _conversation("same-id", "候选人A", "销售管培生", ["你好", "可以接受"])
    second = _conversation("same-id", "候选人A", "HRBP", ["你好", "可以接受"])

    first_session = resolve_or_create_session(repository, first).session
    second_session = resolve_or_create_session(repository, second).session

    assert first_session.id != second_session.id
    assert first_session.position == "销售管培生"
    assert second_session.position == "HRBP"

    no_id = _conversation("", "候选人B", "电气工程师", ["熟悉 PLC", "可以出差"])
    created = resolve_or_create_session(repository, no_id).session
    repository.upsert_messages(created.id, no_id.messages)
    repository.update_recent_fingerprint(created.id, no_id.messages)

    reopened = _conversation(
        "",
        "候选人B",
        "电气工程师",
        ["昨天聊过", "熟悉 PLC", "可以出差", "今天方便"],
    )
    reused = resolve_or_create_session(repository, reopened)

    assert reused.session.id == created.id
    assert reused.confidence == "recent_messages"


def test_artifact_parse_backfills_resume_name_and_hard_link(tmp_path: Path) -> None:
    """下载时先硬关联会话；解析后再补 parsed_name 和 resumes.linked_*。"""

    database = tmp_path / "artifact.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    resume_repo = ResumeRepository(database)
    conversation = _conversation("platform-1", "平台王女士", "膨润土销售", ["我发简历"])
    session = resolve_or_create_session(conversation_repo, conversation).session
    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("王小丽\n13800138000\n本科 膨润土销售经验", encoding="utf-8")

    artifact = artifact_store.record_download(
        session_id=session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="platform-1",
        candidate_name_from_platform="平台王女士",
        position="膨润土销售",
        file_path=resume_file,
        file_hash="hash-1",
        source_kind="attachment",
    )

    assert artifact.parsed_name == ""
    assert artifact.resume_id == ""

    parsed = parse_pending_artifacts(
        artifact_store,
        resume_repo,
        conversation_repo=conversation_repo,
    )

    stored_artifact = artifact_store.get(artifact.id)
    resume = resume_repo.get(parsed[0].resume_id)
    assert stored_artifact is not None
    assert stored_artifact.parsed_name == "王小丽"
    assert stored_artifact.parse_status == "parsed"
    assert resume is not None
    assert resume.parsed_name == "王小丽"
    assert resume.linked_session_id == session.id
    assert resume.linked_platform_conversation_id == "platform-1"


def test_runner_persists_status_and_writes_artifact_after_live_download(tmp_path: Path) -> None:
    """处理消息时写会话状态；51job 真实下载只快写 artifact，不等待解析姓名。"""

    database = tmp_path / "runner.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    page = FakePage(
        conversations=[
            {
                "id": "job51-1",
                "name": "候选人",
                "position": "销售管培生",
                "label": "候选人 销售管培生",
                "latest_message": "可以接受",
                "unread_count": 1,
                "messages": [
                    {"sender": "me", "text": "你是否接受出差？"},
                    {"sender": "other", "text": "可以接受"},
                ],
                "online_resume_bytes": b"%PDF-1.7\ncandidate\n13800138000\n%%EOF",
                "online_resume_filename": "candidate.pdf",
            }
        ]
    )
    adapter = Job51Adapter(page, owner="宋峰峰", dry_run=False)

    state = asyncio.run(
        ConversationRunner(
            adapter,
            rules=_rules(),
            conversation_repository=conversation_repo,
            artifact_store=artifact_store,
        ).run_current()
    )

    session = conversation_repo.get_session(str(state["session_id"]))
    status = conversation_repo.get_status(str(state["session_id"]))
    artifacts = artifact_store.list_pending()
    assert state["next_action"] == "request_resume"
    assert session is not None
    assert session.current_stage == "resume_attachment_downloaded"
    assert status.resume_downloaded is True
    assert status.resume_path
    assert len(artifacts) == 1
    assert artifacts[0].session_id == session.id
    assert artifacts[0].parsed_name == ""


def test_runner_dry_run_does_not_mark_resume_completed(tmp_path: Path) -> None:
    """dry-run 只保留观察状态，不把求简历/下载/linked 状态写成真实完成。"""

    conversation_repo = ConversationRepository(tmp_path / "dry-run.sqlite")
    page = FakePage(
        conversations=[
            {
                "id": "job51-2",
                "name": "候选人",
                "position": "销售管培生",
                "label": "候选人 销售管培生",
                "latest_message": "可以接受",
                "unread_count": 1,
                "messages": [
                    {"sender": "me", "text": "你是否接受出差？"},
                    {"sender": "other", "text": "可以接受"},
                ],
                "online_resume_bytes": b"%PDF-1.7\ncandidate\n%%EOF",
            }
        ]
    )
    adapter = Job51Adapter(page, owner="宋峰峰", dry_run=True)

    state = asyncio.run(
        ConversationRunner(
            adapter,
            rules=_rules(),
            conversation_repository=conversation_repo,
        ).run_current()
    )

    status = conversation_repo.get_status(str(state["session_id"]))
    assert status.resume_requested is False
    assert status.resume_downloaded is False


def test_resume_requested_does_not_block_later_attachment_download(tmp_path: Path) -> None:
    """A prior resume request is not a completion state once a real file appears."""

    database = tmp_path / "requested-then-download.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    platform_conversation_id = "job51-requested"
    bootstrap = Conversation(
        id=platform_conversation_id,
        platform=Platform.JOB51,
        owner="owner",
        candidate=Candidate(name="Candidate", applied_position="DirectRole"),
        messages=[ChatMessage(sender=MessageSender.CANDIDATE, text="hello")],
        should_reply=True,
    )
    session = resolve_or_create_session(conversation_repo, bootstrap).session
    conversation_repo.save_status(
        CandidateStatus(session_id=session.id, resume_requested=True)
    )
    page = FakePage(
        conversations=[
            {
                "id": platform_conversation_id,
                "name": "Candidate",
                "position": "DirectRole",
                "label": "Candidate DirectRole",
                "latest_message": "sent",
                "unread_count": 1,
                "messages": [{"sender": "other", "text": "sent"}],
                "online_resume_bytes": b"%PDF-1.7\ncandidate\n%%EOF",
                "online_resume_filename": "candidate.pdf",
            }
        ]
    )
    adapter = Job51Adapter(page, owner="owner", dry_run=False)

    state = asyncio.run(
        ConversationRunner(
            adapter,
            rules={
                "positionReplies": {
                    "DirectRole": {
                        "directResume": True,
                        "resumeRequestPrompt": "please send resume",
                    }
                },
                "companyKnowledgeBase": {},
            },
            conversation_repository=conversation_repo,
            artifact_store=artifact_store,
        ).run_current()
    )

    status = conversation_repo.get_status(str(state["session_id"]))
    artifacts = artifact_store.list_pending()
    assert state["next_action"] == "request_resume"
    assert state["stage"] != "resume_already_completed"
    assert state["decision"]["result"]["downloaded"] is True
    assert status.resume_requested is True
    assert status.resume_downloaded is True
    assert len(artifacts) == 1


def test_boss_existing_attachment_marks_received_without_download(tmp_path: Path) -> None:
    """BOSS existing attachments are received state, not local download artifacts."""

    database = tmp_path / "boss-received.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    page = FakePage(
        conversations=[
            {
                "id": "boss-received",
                "name": "Candidate",
                "position": "DirectRole",
                "label": "Candidate DirectRole",
                "latest_message": "resume.pdf",
                "unread_count": 1,
                "messages": [{"sender": "other", "text": "resume.pdf"}],
                "has_resume_attachment": True,
                "resume_bytes": b"%PDF-1.7\nboss\n%%EOF",
            }
        ]
    )
    adapter = BossAdapter(page, owner="owner", dry_run=False)

    state = asyncio.run(
        ConversationRunner(
            adapter,
            rules={
                "positionReplies": {
                    "DirectRole": {
                        "directResume": True,
                        "resumeRequestPrompt": "please send resume",
                    }
                },
                "companyKnowledgeBase": {},
            },
            conversation_repository=conversation_repo,
            artifact_store=artifact_store,
        ).run_current()
    )

    status = conversation_repo.get_status(str(state["session_id"]))
    assert state["stage"] == "resume_attachment_received"
    assert state["decision"]["result"]["downloaded"] is False
    assert status.resume_received is True
    assert status.resume_downloaded is False
    assert artifact_store.list_pending() == []


def test_interview_locator_prefers_hard_linked_session(tmp_path: Path) -> None:
    """约面试定位优先使用 resumes.linked_session_id，不靠解析姓名猜测。"""

    database = tmp_path / "interview-link.sqlite"
    conversation_repo = ConversationRepository(database)
    resume_repo = ResumeRepository(database)
    session = resolve_or_create_session(
        conversation_repo,
        _conversation("boss-1", "平台张先生", "投资交易策略研究员", ["我发简历了"]),
    ).session
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

    location = InterviewCenterService(
        repository=resume_repo,
        conversation_repository=conversation_repo,
    ).locate_resume_conversation("resume-linked")

    assert location["requiresConfirmation"] is False
    assert location["session"]["id"] == session.id
    assert location["session"]["candidateName"] == "平台张先生"


def test_interview_locator_requires_confirmation_for_name_only_match(tmp_path: Path) -> None:
    """历史简历没有硬关联时，只返回候选会话，不自动约面试。"""

    database = tmp_path / "interview-name.sqlite"
    conversation_repo = ConversationRepository(database)
    resume_repo = ResumeRepository(database)
    session = resolve_or_create_session(
        conversation_repo,
        _conversation("", "王小丽", "膨润土销售", ["您好", "可以"]),
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

    location = InterviewCenterService(
        repository=resume_repo,
        conversation_repository=conversation_repo,
    ).locate_resume_conversation("resume-name-only")

    assert location["requiresConfirmation"] is True
    assert location["session"] is None
    assert location["candidates"][0]["id"] == session.id


def _conversation(
    conversation_id: str,
    name: str,
    position: str,
    texts: list[str],
) -> Conversation:
    messages = [
        ChatMessage(
            sender=MessageSender.CANDIDATE if index % 2 == 0 else MessageSender.ME,
            text=text,
            raw_text=text,
        )
        for index, text in enumerate(texts)
    ]
    return Conversation(
        id=conversation_id,
        platform=Platform.JOB51,
        owner="宋峰峰",
        candidate=Candidate(name=name, applied_position=position, label=f"{name} {position}"),
        messages=messages,
        latest_message=texts[-1],
        should_reply=True,
    )


def _rules() -> dict[str, object]:
    return {
        "positionReplies": {
            "销售管培生": {
                "category": "sales",
                "screeningQuestions": ["你是否接受出差？"],
            }
        },
        "companyKnowledgeBase": {},
    }
