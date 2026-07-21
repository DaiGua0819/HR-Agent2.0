"""候选人会话状态与简历 artifact 桥接测试。"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import app.domain.resume.repository as resume_repository_module
from app.agent.persistence import ConversationPersistence
from app.agent.runner import ConversationRunner
from app.browser.fake_page import FakePage
from app.core.constants import Platform
from app.db.engine import connect, run_migrations
from app.domain.conversation.dedup import recent_messages_fingerprint
from app.domain.conversation.identity import resolve_or_create_session
from app.domain.conversation.models import CandidateStatus
from app.domain.conversation.repository import ConversationRepository
from app.domain.resume.artifacts import (
    ResumeArtifactStore,
    parse_artifact,
    parse_pending_artifacts,
)
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.evaluation.decision_log import InMemoryDecisionSink
from app.features.interview_center.service import InterviewCenterService
from app.platforms.boss.adapter import BossAdapter
from app.platforms.job51.adapter import Job51Adapter
from app.platforms.types import Candidate, ChatMessage, Conversation, MessageSender
from app.platforms.zhilian.adapter import ZhilianAdapter

from scripts import agent_manager


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
        "message_processing_snapshots",
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


def test_migration_rebuilds_legacy_processing_snapshots_by_canonical_key(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy-processing-snapshots.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE message_processing_snapshots (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              owner TEXT NOT NULL,
              platform TEXT NOT NULL,
              provisional_processing_key TEXT NOT NULL,
              canonical_processing_key TEXT NOT NULL DEFAULT '',
              canonical_session_id TEXT NOT NULL DEFAULT '',
              latest_message_fingerprint TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL,
              action TEXT NOT NULL DEFAULT '',
              stage TEXT NOT NULL DEFAULT '',
              error_reasons TEXT NOT NULL DEFAULT '[]',
              retryable INTEGER NOT NULL DEFAULT 0,
              attempt_count INTEGER NOT NULL DEFAULT 1,
              processed_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(owner, platform, provisional_processing_key)
            );
            """)
        connection.executemany(
            """
            INSERT INTO message_processing_snapshots (
              owner, platform, provisional_processing_key,
              canonical_processing_key, canonical_session_id,
              latest_message_fingerprint, status, stage, retryable,
              attempt_count, processed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "owner",
                    "job51",
                    "candidate-a:09:00",
                    "session|conv-a|message|fingerprint-1",
                    "conv-a",
                    "fingerprint-1",
                    "failed_retryable",
                    "download_not_captured",
                    1,
                    1,
                    "2026-07-19T00:00:00+00:00",
                    "2026-07-19T00:00:01+00:00",
                ),
                (
                    "owner",
                    "job51",
                    "candidate-a:09:01",
                    "session|conv-a|message|fingerprint-1",
                    "conv-a",
                    "fingerprint-1",
                    "failed_retryable",
                    "download_not_captured",
                    1,
                    2,
                    "2026-07-19T00:00:02+00:00",
                    "2026-07-19T00:00:03+00:00",
                ),
            ],
        )

    run_migrations(database)

    with connect(database) as connection:
        rows = connection.execute("""
            SELECT snapshot_key, provisional_processing_key, attempt_count,
                   processed_at, updated_at
            FROM message_processing_snapshots
            """).fetchall()
        connection.execute(
            """
            INSERT INTO message_processing_snapshots (
              owner, platform, snapshot_key, provisional_processing_key,
              canonical_processing_key, canonical_session_id,
              latest_message_fingerprint, status, processed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "owner",
                "job51",
                "session|conv-a|message|fingerprint-2",
                "candidate-a:09:01",
                "session|conv-a|message|fingerprint-2",
                "conv-a",
                "fingerprint-2",
                "completed",
                "2026-07-19T00:01:00+00:00",
                "2026-07-19T00:01:00+00:00",
            ),
        )
        snapshot_count = connection.execute(
            "SELECT COUNT(*) FROM message_processing_snapshots"
        ).fetchone()[0]

    assert [tuple(row) for row in rows] == [
        (
            "session|conv-a|message|fingerprint-1",
            "candidate-a:09:01",
            3,
            "2026-07-19T00:00:00+00:00",
            "2026-07-19T00:00:03+00:00",
        )
    ]
    assert snapshot_count == 2


def test_processing_snapshot_migration_is_safe_for_concurrent_workers(
    tmp_path: Path,
) -> None:
    for attempt in range(30):
        database = tmp_path / f"concurrent-snapshot-migration-{attempt}.sqlite"
        with sqlite3.connect(database) as connection:
            connection.executescript("""
                CREATE TABLE message_processing_snapshots (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  owner TEXT NOT NULL,
                  platform TEXT NOT NULL,
                  provisional_processing_key TEXT NOT NULL,
                  canonical_processing_key TEXT NOT NULL DEFAULT '',
                  canonical_session_id TEXT NOT NULL DEFAULT '',
                  latest_message_fingerprint TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL,
                  action TEXT NOT NULL DEFAULT '',
                  stage TEXT NOT NULL DEFAULT '',
                  error_reasons TEXT NOT NULL DEFAULT '[]',
                  retryable INTEGER NOT NULL DEFAULT 0,
                  attempt_count INTEGER NOT NULL DEFAULT 1,
                  processed_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(owner, platform, provisional_processing_key)
                );
                """)
        start = threading.Barrier(2)

        def migrate(
            current_database: Path = database,
            barrier: threading.Barrier = start,
        ) -> None:
            barrier.wait(timeout=5)
            agent_manager.ensure_processing_snapshot_table(current_database)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(migrate) for _ in range(2)]
            for future in futures:
                future.result()

        with connect(database) as connection:
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(message_processing_snapshots)"
                ).fetchall()
            }
        assert "snapshot_key" in columns


def test_conversation_repository_loads_durable_processing_exclusions(
    tmp_path: Path,
) -> None:
    database = tmp_path / "processing-exclusions.sqlite"
    repository = ConversationRepository(database)
    with connect(database) as connection:
        connection.execute(
            """
            INSERT INTO message_processing_snapshots (
              owner, platform, snapshot_key, provisional_processing_key,
              canonical_processing_key, status, retryable, attempt_count,
              processed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'completed', 0, 1, ?, ?)
            """,
            (
                "owner",
                "job51",
                "session|conv-a|message|fingerprint-1",
                "candidate-a:message-1",
                "session|conv-a|message|fingerprint-1",
                "2026-07-19T00:00:00+00:00",
                "2026-07-19T00:00:00+00:00",
            ),
        )
        connection.commit()

    assert repository.processing_snapshot_exclusions(
        owner="owner",
        platform="job51",
    ) == {
        "candidate-a:message-1",
        "session|conv-a|message|fingerprint-1",
    }


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


def test_fingerprint_ignores_volatile_raw_metadata() -> None:
    relative_metadata = [
        ChatMessage(
            sender=MessageSender.CANDIDATE,
            text="Hello, I can interview tomorrow.",
            raw_text="2 minutes ago unread Hello, I can interview tomorrow.",
        ),
        ChatMessage(
            sender=MessageSender.ME,
            text="What time works for you?",
            raw_text="just now sent What time works for you?",
        ),
    ]
    absolute_metadata = [
        ChatMessage(
            sender=MessageSender.CANDIDATE,
            text="Hello, I can interview tomorrow.",
            raw_text="2026-07-21 09:30 read Hello, I can interview tomorrow.",
        ),
        ChatMessage(
            sender=MessageSender.ME,
            text="What time works for you?",
            raw_text="2026-07-21 09:31 read What time works for you?",
        ),
    ]

    assert recent_messages_fingerprint(relative_metadata) == recent_messages_fingerprint(
        absolute_metadata
    )


def test_fingerprint_includes_raw_text_only_messages() -> None:
    messages = [
        ChatMessage(
            sender=MessageSender.CANDIDATE,
            text="",
            raw_text="  raw-text-only   message  ",
        )
    ]

    assert recent_messages_fingerprint(messages) == hashlib.sha256(
        b"raw-text-only message"
    ).hexdigest()


def test_fingerprint_uses_raw_text_when_text_is_whitespace() -> None:
    messages = [
        ChatMessage(
            sender=MessageSender.CANDIDATE,
            text="   ",
            raw_text="  raw fallback after normalization  ",
        )
    ]

    assert recent_messages_fingerprint(messages) == hashlib.sha256(
        b"raw fallback after normalization"
    ).hexdigest()


def test_no_id_session_reuses_legacy_raw_first_fingerprint(tmp_path: Path) -> None:
    database = tmp_path / "legacy-raw-first.sqlite"
    repository = ConversationRepository(database)
    initial = Conversation(
        id="",
        platform=Platform.JOB51,
        owner="owner",
        candidate=Candidate(name="Alice", applied_position="Backend Engineer"),
        messages=[
            ChatMessage(
                sender=MessageSender.CANDIDATE,
                text="Initial normalized message.",
                raw_text="2 minutes ago   unread   hello",
            )
        ],
        should_reply=True,
    )
    created = resolve_or_create_session(repository, initial)
    legacy_fingerprint = hashlib.sha256(b"2 minutes ago unread hello").hexdigest()
    with connect(database) as connection:
        connection.execute(
            """
            UPDATE conversation_sessions
            SET recent_messages_fingerprint = ?
            WHERE id = ?
            """,
            (legacy_fingerprint, created.session.id),
        )
        connection.commit()
    current = Conversation(
        id="",
        platform=Platform.JOB51,
        owner="owner",
        candidate=Candidate(name="Alice", applied_position="Backend Engineer"),
        messages=[
            ChatMessage(
                sender=MessageSender.CANDIDATE,
                text="Current normalized message changed.",
                raw_text="2 minutes ago unread hello",
            )
        ],
        should_reply=True,
    )

    reopened = resolve_or_create_session(repository, current)

    assert reopened.session.id == created.session.id
    assert reopened.confidence == "recent_messages"


def test_stable_platform_identity_accepts_same_candidate_with_evolved_messages(
    tmp_path: Path,
) -> None:
    repository = ConversationRepository(tmp_path / "stable-same-candidate.sqlite")
    initial = Conversation(
        id="boss-conversation-123",
        platform=Platform.BOSS,
        owner="owner",
        candidate=Candidate(name="Alice Smith", applied_position="Backend Engineer"),
        messages=[
            ChatMessage(
                sender=MessageSender.CANDIDATE,
                text="I am interested in this role.",
                raw_text="2 minutes ago unread I am interested in this role.",
            )
        ],
        should_reply=True,
    )
    created = resolve_or_create_session(repository, initial)
    evolved = Conversation(
        id="boss-conversation-123",
        platform=Platform.BOSS,
        owner="owner",
        candidate=Candidate(name=" aliceSMITH ", applied_position="Backend Engineer"),
        messages=[
            ChatMessage(
                sender=MessageSender.CANDIDATE,
                text="I uploaded my latest resume.",
                raw_text="2026-07-21 09:30 read I uploaded my latest resume.",
            )
        ],
        should_reply=True,
    )

    reopened = resolve_or_create_session(repository, evolved)

    assert reopened.session.id == created.session.id
    assert reopened.warnings == []


def test_stable_platform_identity_warns_when_candidate_name_changes(
    tmp_path: Path,
) -> None:
    repository = ConversationRepository(tmp_path / "stable-changed-candidate.sqlite")
    initial = Conversation(
        id="boss-conversation-456",
        platform=Platform.BOSS,
        owner="owner",
        candidate=Candidate(
            name="Alice Smith",
            applied_position="Backend Engineer",
            label="Alice Smith Backend Engineer original conversation",
        ),
        messages=[
            ChatMessage(
                sender=MessageSender.CANDIDATE,
                text="I am interested in this role.",
            )
        ],
        should_reply=True,
    )
    created = resolve_or_create_session(repository, initial)
    first_changed_candidate = Conversation(
        id="boss-conversation-456",
        platform=Platform.BOSS,
        owner="owner",
        candidate=Candidate(
            name="Bob Jones",
            applied_position="Backend Engineer",
            label="Bob Jones Backend Engineer conflicting conversation",
        ),
        messages=[
            ChatMessage(
                sender=MessageSender.CANDIDATE,
                text="This is a different candidate conversation.",
            )
        ],
        should_reply=True,
    )
    second_changed_candidate = Conversation(
        id="boss-conversation-456",
        platform=Platform.BOSS,
        owner="owner",
        candidate=Candidate(
            name="Bob Jones",
            applied_position="Backend Engineer",
            label="Bob Jones Backend Engineer evolved conversation",
        ),
        messages=[
            ChatMessage(
                sender=MessageSender.CANDIDATE,
                text="These are Bob's evolved messages.",
            )
        ],
        should_reply=True,
    )

    first_reopened = resolve_or_create_session(repository, first_changed_candidate)
    second_reopened = resolve_or_create_session(repository, second_changed_candidate)
    persisted = repository.get_session(created.session.id)

    assert first_reopened.session.id == created.session.id
    assert "recent_messages_not_matched" in first_reopened.warnings
    assert "recent_messages_not_matched" in second_reopened.warnings
    assert persisted is not None
    assert persisted.candidate_name == created.session.candidate_name
    assert persisted.label == created.session.label
    assert (
        persisted.recent_messages_fingerprint
        == created.session.recent_messages_fingerprint
    )


def test_stable_platform_identity_warns_on_name_change_without_fingerprint(
    tmp_path: Path,
) -> None:
    repository = ConversationRepository(tmp_path / "empty-fingerprint-name-change.sqlite")
    initial = Conversation(
        id="boss-conversation-empty-fingerprint",
        platform=Platform.BOSS,
        owner="owner",
        candidate=Candidate(name="Alice", applied_position="Backend Engineer"),
        messages=[],
        should_reply=False,
    )
    created = resolve_or_create_session(repository, initial)
    changed = Conversation(
        id="boss-conversation-empty-fingerprint",
        platform=Platform.BOSS,
        owner="owner",
        candidate=Candidate(name="Bob", applied_position="Backend Engineer"),
        messages=[],
        should_reply=False,
    )

    reopened = resolve_or_create_session(repository, changed)
    persisted = repository.get_session(created.session.id)

    assert "recent_messages_not_matched" in reopened.warnings
    assert persisted is not None
    assert persisted.candidate_name == "Alice"


def test_persistence_preserves_identity_after_repeated_candidate_conflicts(
    tmp_path: Path,
) -> None:
    repository = ConversationRepository(tmp_path / "persistence-conflict.sqlite")
    persistence = ConversationPersistence(
        repository=repository,
        artifact_store=None,
        adapter=SimpleNamespace(dry_run=False),
    )
    initial = Conversation(
        id="boss-persistence-conflict",
        platform=Platform.BOSS,
        owner="owner",
        candidate=Candidate(name="Alice", applied_position="Backend Engineer"),
        messages=[ChatMessage(sender=MessageSender.CANDIDATE, text="Alice message")],
        should_reply=True,
    )
    initial_state: dict[str, object] = {}
    persistence.attach(initial_state, initial)
    session_id = str(initial_state["session_id"])
    trusted = repository.get_session(session_id)
    assert trusted is not None

    warning_states = []
    for message in ("Bob first message", "Bob second message"):
        state: dict[str, object] = {}
        persistence.attach(
            state,
            Conversation(
                id="boss-persistence-conflict",
                platform=Platform.BOSS,
                owner="owner",
                candidate=Candidate(name="Bob", applied_position="Backend Engineer"),
                messages=[ChatMessage(sender=MessageSender.CANDIDATE, text=message)],
                should_reply=True,
            ),
        )
        warning_states.append(state)

    persisted = repository.get_session(session_id)

    assert all(
        "recent_messages_not_matched" in state["identity_warnings"]
        for state in warning_states
    )
    assert persisted is not None
    assert persisted.candidate_name == trusted.candidate_name
    assert persisted.recent_messages_fingerprint == trusted.recent_messages_fingerprint


def test_status_label_platform_id_does_not_merge_candidates(tmp_path: Path) -> None:
    """Status labels like [read] are not stable platform conversation ids."""

    repository = ConversationRepository(tmp_path / "status-label-id.sqlite")
    first = Conversation(
        id="[已读]",
        platform=Platform.ZHILIAN,
        owner="owner",
        candidate=Candidate(name="Alice", applied_position="AI应用开发实习生"),
        messages=[ChatMessage(sender=MessageSender.CANDIDATE, text="hello from alice")],
        should_reply=True,
    )
    second = Conversation(
        id="[已读]",
        platform=Platform.ZHILIAN,
        owner="owner",
        candidate=Candidate(name="Bob", applied_position="AI应用开发实习生"),
        messages=[ChatMessage(sender=MessageSender.CANDIDATE, text="hello from bob")],
        should_reply=True,
    )

    first_session = resolve_or_create_session(repository, first).session
    second_session = resolve_or_create_session(repository, second).session

    assert first_session.id != second_session.id
    assert first_session.platform_conversation_id == ""
    assert second_session.platform_conversation_id == ""


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


def test_artifact_parse_extracts_docx_text(tmp_path: Path) -> None:
    database = tmp_path / "docx-artifact.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    resume_repo = ResumeRepository(database)
    conversation = _conversation("docx-1", "仲献平", "AI产品经理", ["附件简历"])
    session = resolve_or_create_session(conversation_repo, conversation).session
    resume_file = tmp_path / "candidate.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>个人信息</w:t></w:r></w:p>
        <w:p><w:r><w:t>姓 名：仲献平 性 别：男 出 生：19880702</w:t></w:r></w:p>
        <w:p><w:r><w:t>AI 产品经理</w:t></w:r></w:p>
      </w:body>
    </w:document>
    """
    with zipfile.ZipFile(resume_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", document_xml)

    artifact = artifact_store.record_download(
        session_id=session.id,
        platform=Platform.ZHILIAN.value,
        owner="宋峰峰",
        platform_conversation_id="docx-1",
        candidate_name_from_platform="仲献平",
        position="AI产品经理",
        file_path=resume_file,
        file_hash="docx-hash",
        source_kind="attachment",
    )

    parsed = parse_pending_artifacts(artifact_store, resume_repo)
    resume = resume_repo.get(parsed[0].resume_id)

    assert artifact_store.get(artifact.id).parse_status == "parsed"  # type: ignore[union-attr]
    assert resume is not None
    assert resume.parsed_name == "仲献平"
    assert "AI 产品经理" in str(resume.payload.get("rawText") or "")


def test_parse_artifact_parses_only_the_requested_download(tmp_path: Path) -> None:
    database = tmp_path / "single-artifact.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    resume_repo = ResumeRepository(database)
    first_session = resolve_or_create_session(
        conversation_repo,
        _conversation("single-1", "平台候选人一", "AI产品经理", ["附件简历"]),
    ).session
    second_session = resolve_or_create_session(
        conversation_repo,
        _conversation("single-2", "平台候选人二", "运营B", ["附件简历"]),
    ).session
    first_file = tmp_path / "first.txt"
    second_file = tmp_path / "second.txt"
    first_file.write_text("姓名：王小丽\nAI产品经理", encoding="utf-8")
    second_file.write_text("姓名：李小明\nB端运营", encoding="utf-8")
    first = artifact_store.record_download(
        session_id=first_session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="single-1",
        candidate_name_from_platform="平台候选人一",
        position="AI产品经理",
        file_path=first_file,
        file_hash="single-hash-1",
        source_kind="attachment",
    )
    second = artifact_store.record_download(
        session_id=second_session.id,
        platform=Platform.ZHILIAN.value,
        owner="宋峰峰",
        platform_conversation_id="single-2",
        candidate_name_from_platform="平台候选人二",
        position="运营B",
        file_path=second_file,
        file_hash="single-hash-2",
        source_kind="attachment",
    )

    parsed = parse_artifact(artifact_store, resume_repo, second)

    assert parsed.parse_status == "parsed"
    assert parsed.parsed_name == "李小明"
    assert artifact_store.get(first.id).parse_status == "pending"  # type: ignore[union-attr]
    assert resume_repo.count() == 1


def test_parse_artifact_is_idempotent_after_success(tmp_path: Path) -> None:
    database = tmp_path / "idempotent-artifact.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    resume_repo = ResumeRepository(database)
    session = resolve_or_create_session(
        conversation_repo,
        _conversation(
            "idempotent-conversation",
            "平台王女士",
            "AI产品经理",
            ["附件简历"],
        ),
    ).session
    resume_file = tmp_path / "idempotent.txt"
    resume_file.write_text("姓名：王小丽\nAI产品经理", encoding="utf-8")
    artifact = artifact_store.record_download(
        session_id=session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="idempotent-conversation",
        candidate_name_from_platform="平台王女士",
        position="AI产品经理",
        file_path=resume_file,
        file_hash="idempotent-hash",
        source_kind="attachment",
    )

    first = parse_artifact(artifact_store, resume_repo, artifact)
    second = parse_artifact(artifact_store, resume_repo, artifact)

    assert first.parse_status == "parsed"
    assert second.resume_id == first.resume_id
    assert resume_repo.count() == 1


def test_parse_artifact_concurrent_calls_create_one_resume(tmp_path: Path) -> None:
    database = tmp_path / "concurrent-parse.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    resume_repo = ResumeRepository(database)
    session = resolve_or_create_session(
        conversation_repo,
        _conversation("concurrent-parse", "平台王女士", "AI产品经理", ["附件简历"]),
    ).session
    resume_file = tmp_path / "concurrent-parse.txt"
    resume_file.write_text("姓名：王小丽\nAI产品经理", encoding="utf-8")
    artifact = artifact_store.record_download(
        session_id=session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="concurrent-parse",
        candidate_name_from_platform="平台王女士",
        position="AI产品经理",
        file_path=resume_file,
        file_hash="concurrent-parse-hash",
        source_kind="attachment",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        parsed = list(
            executor.map(
                lambda _: parse_artifact(artifact_store, resume_repo, artifact),
                range(2),
            )
        )

    assert {item.parse_status for item in parsed} == {"parsed"}
    assert len({item.resume_id for item in parsed}) == 1
    assert resume_repo.count() == 1


def test_parse_artifact_failure_does_not_touch_other_pending_downloads(
    tmp_path: Path,
) -> None:
    database = tmp_path / "failed-artifact.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    resume_repo = ResumeRepository(database)
    missing_session = resolve_or_create_session(
        conversation_repo,
        _conversation(
            "failed-conversation",
            "缺失文件候选人",
            "AI产品经理",
            ["附件简历"],
        ),
    ).session
    untouched_session = resolve_or_create_session(
        conversation_repo,
        _conversation(
            "untouched-conversation",
            "待处理候选人",
            "运营B",
            ["附件简历"],
        ),
    ).session
    missing = artifact_store.record_download(
        session_id=missing_session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="failed-conversation",
        candidate_name_from_platform="缺失文件候选人",
        position="AI产品经理",
        file_path=tmp_path / "missing.pdf",
        file_hash="failed-hash",
        source_kind="attachment",
    )
    untouched_file = tmp_path / "untouched.txt"
    untouched_file.write_text("姓名：李小明", encoding="utf-8")
    untouched = artifact_store.record_download(
        session_id=untouched_session.id,
        platform=Platform.ZHILIAN.value,
        owner="宋峰峰",
        platform_conversation_id="untouched-conversation",
        candidate_name_from_platform="待处理候选人",
        position="运营B",
        file_path=untouched_file,
        file_hash="untouched-hash",
        source_kind="attachment",
    )

    failed = parse_artifact(artifact_store, resume_repo, missing)

    assert failed.parse_status == "failed"
    assert failed.error
    assert artifact_store.get(untouched.id).parse_status == "pending"  # type: ignore[union-attr]
    assert resume_repo.count() == 0


def test_parse_artifact_rolls_back_resume_when_status_update_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "atomic-artifact.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    resume_repo = ResumeRepository(database)
    session = resolve_or_create_session(
        conversation_repo,
        _conversation("atomic-conversation", "平台王女士", "AI产品经理", ["附件简历"]),
    ).session
    resume_file = tmp_path / "atomic.txt"
    resume_file.write_text("姓名：王小丽\nAI产品经理", encoding="utf-8")
    artifact = artifact_store.record_download(
        session_id=session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="atomic-conversation",
        candidate_name_from_platform="平台王女士",
        position="AI产品经理",
        file_path=resume_file,
        file_hash="atomic-hash",
        source_kind="attachment",
    )

    def fail_status_update(*args, **kwargs) -> None:
        _ = args, kwargs
        raise RuntimeError("status update failed")

    monkeypatch.setattr(artifact_store, "mark_parsed", fail_status_update)

    failed = parse_artifact(artifact_store, resume_repo, artifact)

    assert failed.parse_status == "failed"
    assert "status update failed" in failed.error
    assert resume_repo.count() == 0


def test_failed_artifact_uses_latest_successful_redownload(tmp_path: Path) -> None:
    database = tmp_path / "retry-artifact.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    resume_repo = ResumeRepository(database)
    session = resolve_or_create_session(
        conversation_repo,
        _conversation("retry-conversation", "平台王女士", "AI产品经理", ["附件简历"]),
    ).session
    missing_file = tmp_path / "missing.pdf"
    artifact = artifact_store.record_download(
        session_id=session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="retry-conversation",
        candidate_name_from_platform="平台王女士",
        position="AI产品经理",
        file_path=missing_file,
        file_hash="failed-download-hash",
        source_kind="attachment",
    )
    assert parse_artifact(artifact_store, resume_repo, artifact).parse_status == "failed"
    replacement_file = tmp_path / "replacement.txt"
    replacement_file.write_text("姓名：王小丽\nAI产品经理", encoding="utf-8")

    replacement = artifact_store.record_download(
        session_id=session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="retry-conversation",
        candidate_name_from_platform="平台王女士",
        position="AI产品经理",
        file_path=replacement_file,
        file_hash="replacement-download-hash",
        source_kind="attachment",
    )
    parsed = parse_artifact(artifact_store, resume_repo, replacement)

    assert replacement.file_path == str(replacement_file)
    assert replacement.file_hash == "replacement-download-hash"
    assert parsed.parse_status == "parsed"
    assert parsed.parsed_name == "王小丽"
    assert resume_repo.count() == 1


def test_persistence_does_not_rerun_migrations_during_resume_download(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "no-download-migration.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    persistence = ConversationPersistence(
        repository=conversation_repo,
        artifact_store=artifact_store,
        adapter=SimpleNamespace(dry_run=False),
    )
    state: dict[str, object] = {}
    persistence.attach(
        state,
        _conversation("no-migration", "平台王女士", "AI产品经理", ["附件简历"]),
    )
    resume_file = tmp_path / "no-migration.txt"
    resume_file.write_text("姓名：王小丽\nAI产品经理", encoding="utf-8")

    def fail_migration(*args, **kwargs) -> None:
        _ = args, kwargs
        raise AssertionError("download path reran migrations")

    monkeypatch.setattr(resume_repository_module, "run_migrations", fail_migration)
    result = {
        "downloaded": True,
        "filePath": str(resume_file),
        "fileHash": "no-migration-hash",
        "sourceKind": "attachment",
    }

    persistence.finish(
        state,
        action="request_resume",
        reason="resume_attachment_downloaded",
        extra={"result": result},
    )

    artifact = artifact_store.find_business_download(
        session_id=str(state["session_id"]),
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="no-migration",
        position="AI产品经理",
    )
    assert artifact is not None
    assert artifact.parse_status == "parsed"


def test_persistence_surfaces_resume_parse_failure_to_manager(
    tmp_path: Path,
) -> None:
    database = tmp_path / "visible-parse-failure.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    persistence = ConversationPersistence(
        repository=conversation_repo,
        artifact_store=artifact_store,
        adapter=SimpleNamespace(dry_run=False),
    )
    state: dict[str, object] = {}
    persistence.attach(
        state,
        _conversation("visible-failure", "平台王女士", "AI产品经理", ["附件简历"]),
    )
    result = {
        "downloaded": True,
        "filePath": str(tmp_path / "missing.pdf"),
        "fileHash": "visible-failure-hash",
        "sourceKind": "attachment",
    }

    persistence.finish(
        state,
        action="request_resume",
        reason="resume_attachment_downloaded",
        extra={"result": result},
    )
    classification = agent_manager.classify_result(
        {
            "accepted": True,
            "nextAction": "request_resume",
            "stage": "resume_attachment_downloaded",
            "decision": {
                "action": "request_resume",
                "reason": "resume_attachment_downloaded",
                "result": result,
            },
        }
    )

    assert result["artifactParseStatus"] == "failed"
    assert result["failureReason"] == "resume_artifact_parse_failed"
    assert result["artifactParseError"]
    assert classification.is_anomaly is True
    assert "resume_artifact_parse_failed" in classification.reasons


def test_artifact_record_failure_does_not_persist_false_resume_completion(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "artifact-record-failed.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    persistence = ConversationPersistence(
        repository=conversation_repo,
        artifact_store=artifact_store,
        adapter=SimpleNamespace(dry_run=False),
    )
    state: dict[str, object] = {}
    persistence.attach(
        state,
        _conversation("record-failed", "平台王女士", "AI产品经理", ["附件简历"]),
    )
    resume_file = tmp_path / "record-failed.txt"
    resume_file.write_text("姓名：王小丽\nAI产品经理", encoding="utf-8")

    def fail_record_download(*args, **kwargs):
        _ = args, kwargs
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(artifact_store, "record_download", fail_record_download)
    result = {
        "downloaded": True,
        "filePath": str(resume_file),
        "fileHash": "record-failed-hash",
        "sourceKind": "attachment",
    }

    persistence.finish(
        state,
        action="request_resume",
        reason="resume_attachment_downloaded",
        extra={"result": result},
    )
    status = conversation_repo.get_status(str(state["session_id"]))

    assert status.resume_downloaded is False
    assert result["artifactParseStatus"] == "failed"
    assert result["failureReason"] == "resume_artifact_parse_failed"
    assert persistence.has_resume_downloaded() is False


def test_resume_completion_retries_pending_artifact_before_skipping(
    tmp_path: Path,
) -> None:
    database = tmp_path / "retry-pending-on-preflight.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    persistence = ConversationPersistence(
        repository=conversation_repo,
        artifact_store=artifact_store,
        adapter=SimpleNamespace(dry_run=False),
    )
    state: dict[str, object] = {}
    persistence.attach(
        state,
        _conversation("pending-preflight", "平台王女士", "AI产品经理", ["附件简历"]),
    )
    session_id = str(state["session_id"])
    resume_file = tmp_path / "pending-preflight.txt"
    resume_file.write_text("姓名：王小丽\nAI产品经理", encoding="utf-8")
    artifact = artifact_store.record_download(
        session_id=session_id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="pending-preflight",
        candidate_name_from_platform="平台王女士",
        position="AI产品经理",
        file_path=resume_file,
        file_hash="pending-preflight-hash",
        source_kind="attachment",
    )
    conversation_repo.save_status(CandidateStatus(session_id=session_id, resume_downloaded=True))
    persistence.candidate_status = conversation_repo.get_status(session_id)

    assert persistence.has_resume_downloaded() is True
    parsed = artifact_store.get(artifact.id)
    assert parsed is not None
    assert parsed.parse_status == "parsed"
    assert ResumeRepository(database).get(parsed.resume_id) is not None


def test_artifact_store_reuses_business_identity_when_dynamic_pdf_hash_changes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "dynamic-pdf.sqlite"
    conversation_repo = ConversationRepository(database)
    store = ResumeArtifactStore(database)
    first_session = resolve_or_create_session(
        conversation_repo,
        _conversation("dynamic-one", "胡泽群", "AI产品经理", ["第一版简历"]),
    ).session
    first_file = tmp_path / "first.pdf"
    second_file = tmp_path / "second.pdf"
    first_file.write_bytes(b"%PDF-1.7\nwatermark-one\n%%EOF")
    second_file.write_bytes(b"%PDF-1.7\nwatermark-two\n%%EOF")

    first = store.record_download(
        session_id=first_session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="",
        candidate_name_from_platform="胡泽群",
        position="AI产品经理",
        file_path=first_file,
        file_hash="hash-one",
        source_kind="online_resume",
    )
    second = store.record_download(
        session_id=first_session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="",
        candidate_name_from_platform="胡泽群",
        position="AI产品经理",
        file_path=second_file,
        file_hash="hash-two",
        source_kind="online_resume",
    )

    assert second.id == first.id
    assert len(store.list_pending()) == 1


def test_artifact_store_serializes_concurrent_downloads_for_same_session(
    tmp_path: Path,
) -> None:
    database = tmp_path / "concurrent-download.sqlite"
    conversation_repo = ConversationRepository(database)
    store = ResumeArtifactStore(database)
    session = resolve_or_create_session(
        conversation_repo,
        _conversation("concurrent", "胡泽群", "AI产品经理", ["发送简历"]),
    ).session
    files = [tmp_path / "concurrent-one.pdf", tmp_path / "concurrent-two.pdf"]
    files[0].write_bytes(b"%PDF-1.7\nconcurrent-one\n%%EOF")
    files[1].write_bytes(b"%PDF-1.7\nconcurrent-two\n%%EOF")

    def record(index: int):  # noqa: ANN202
        return store.record_download(
            session_id=session.id,
            platform=Platform.JOB51.value,
            owner="宋峰峰",
            platform_conversation_id="concurrent",
            candidate_name_from_platform="胡泽群",
            position="AI产品经理",
            file_path=files[index],
            file_hash=f"concurrent-hash-{index}",
            source_kind="online_resume",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        artifacts = list(executor.map(record, (0, 1)))

    assert artifacts[0].id == artifacts[1].id
    assert len(store.list_pending()) == 1


def test_artifact_store_keeps_same_name_separate_across_different_jobs(
    tmp_path: Path,
) -> None:
    database = tmp_path / "different-jobs.sqlite"
    conversation_repo = ConversationRepository(database)
    store = ResumeArtifactStore(database)
    first_session = resolve_or_create_session(
        conversation_repo,
        _conversation("same-platform-id", "张伟", "AI产品经理", ["第一份简历"]),
    ).session
    second_session = resolve_or_create_session(
        conversation_repo,
        _conversation("same-platform-id", "张伟", "B端社交媒体运营", ["第二份简历"]),
    ).session
    first_file = tmp_path / "job-one.pdf"
    second_file = tmp_path / "job-two.pdf"
    first_file.write_bytes(b"%PDF-1.7\njob-one\n%%EOF")
    second_file.write_bytes(b"%PDF-1.7\njob-two\n%%EOF")

    first = store.record_download(
        session_id=first_session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="same-platform-id",
        candidate_name_from_platform="张伟",
        position="AI产品经理",
        file_path=first_file,
        file_hash="job-one-hash",
        source_kind="online_resume",
    )
    second = store.record_download(
        session_id=second_session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="same-platform-id",
        candidate_name_from_platform="张伟",
        position="B端社交媒体运营",
        file_path=second_file,
        file_hash="job-two-hash",
        source_kind="online_resume",
    )

    assert first.id != second.id
    assert len(store.list_pending()) == 2


def test_artifact_store_does_not_merge_masked_names_without_stable_id(
    tmp_path: Path,
) -> None:
    database = tmp_path / "masked-names.sqlite"
    conversation_repo = ConversationRepository(database)
    store = ResumeArtifactStore(database)
    first_session = resolve_or_create_session(
        conversation_repo,
        _conversation("masked-one", "张女士", "AI产品经理", ["第一位候选人"]),
    ).session
    second_session = resolve_or_create_session(
        conversation_repo,
        _conversation("masked-two", "张女士", "AI产品经理", ["第二位候选人"]),
    ).session
    first_file = tmp_path / "masked-one.pdf"
    second_file = tmp_path / "masked-two.pdf"
    first_file.write_bytes(b"%PDF-1.7\nmasked-one\n%%EOF")
    second_file.write_bytes(b"%PDF-1.7\nmasked-two\n%%EOF")

    first = store.record_download(
        session_id=first_session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="",
        candidate_name_from_platform="张女士",
        position="AI产品经理",
        file_path=first_file,
        file_hash="masked-one-hash",
        source_kind="online_resume",
    )
    second = store.record_download(
        session_id=second_session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="",
        candidate_name_from_platform="张女士",
        position="AI产品经理",
        file_path=second_file,
        file_hash="masked-two-hash",
        source_kind="online_resume",
    )

    assert first.id != second.id
    assert len(store.list_pending()) == 2


def test_artifact_store_does_not_merge_full_names_without_stable_id(
    tmp_path: Path,
) -> None:
    database = tmp_path / "same-full-name.sqlite"
    conversation_repo = ConversationRepository(database)
    store = ResumeArtifactStore(database)
    first_session = resolve_or_create_session(
        conversation_repo,
        _conversation("full-one", "张伟", "AI产品经理", ["第一位候选人"]),
    ).session
    second_session = resolve_or_create_session(
        conversation_repo,
        _conversation("full-two", "张伟", "AI产品经理", ["第二位候选人"]),
    ).session
    first_file = tmp_path / "full-one.pdf"
    second_file = tmp_path / "full-two.pdf"
    first_file.write_bytes(b"%PDF-1.7\nfull-one\n%%EOF")
    second_file.write_bytes(b"%PDF-1.7\nfull-two\n%%EOF")

    first = store.record_download(
        session_id=first_session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="",
        candidate_name_from_platform="张伟",
        position="AI产品经理",
        file_path=first_file,
        file_hash="full-one-hash",
        source_kind="online_resume",
    )
    second = store.record_download(
        session_id=second_session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="",
        candidate_name_from_platform="张伟",
        position="AI产品经理",
        file_path=second_file,
        file_hash="full-two-hash",
        source_kind="online_resume",
    )

    assert first.id != second.id
    assert len(store.list_pending()) == 2


def test_artifact_store_does_not_merge_stable_id_when_position_is_missing(
    tmp_path: Path,
) -> None:
    database = tmp_path / "missing-position.sqlite"
    conversation_repo = ConversationRepository(database)
    store = ResumeArtifactStore(database)
    first_session = resolve_or_create_session(
        conversation_repo,
        _conversation("same-platform-id", "张伟", "AI产品经理", ["第一份简历"]),
    ).session
    second_session = resolve_or_create_session(
        conversation_repo,
        _conversation("same-platform-id", "张伟", "", ["第二份简历"]),
    ).session
    first_file = tmp_path / "known-position.pdf"
    second_file = tmp_path / "missing-position.pdf"
    first_file.write_bytes(b"%PDF-1.7\nknown-position\n%%EOF")
    second_file.write_bytes(b"%PDF-1.7\nmissing-position\n%%EOF")

    first = store.record_download(
        session_id=first_session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="same-platform-id",
        candidate_name_from_platform="张伟",
        position="AI产品经理",
        file_path=first_file,
        file_hash="known-position-hash",
        source_kind="online_resume",
    )
    second = store.record_download(
        session_id=second_session.id,
        platform=Platform.JOB51.value,
        owner="宋峰峰",
        platform_conversation_id="same-platform-id",
        candidate_name_from_platform="张伟",
        position="",
        file_path=second_file,
        file_hash="missing-position-hash",
        source_kind="online_resume",
    )

    assert first.id != second.id
    assert len(store.list_pending()) == 2


def test_runner_skips_download_when_current_session_already_has_artifact(
    tmp_path: Path,
) -> None:
    database = tmp_path / "business-resume-complete.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    old_conversation = Conversation(
        id="old-platform-conversation",
        platform=Platform.JOB51,
        owner="owner",
        candidate=Candidate(name="胡泽群", applied_position="AI产品经理"),
        messages=[ChatMessage(sender=MessageSender.CANDIDATE, text="旧简历")],
        should_reply=True,
    )
    old_session = resolve_or_create_session(conversation_repo, old_conversation).session
    existing_file = tmp_path / "existing.pdf"
    existing_file.write_bytes(b"%PDF-1.7\nexisting\n%%EOF")
    artifact_store.record_download(
        session_id=old_session.id,
        platform=Platform.JOB51.value,
        owner="owner",
        platform_conversation_id="old-platform-conversation",
        candidate_name_from_platform="胡泽群",
        position="AI产品经理",
        file_path=existing_file,
        file_hash="existing-hash",
        source_kind="online_resume",
    )
    page = FakePage(
        conversations=[
            {
                "id": "old-platform-conversation",
                "name": "胡泽群",
                "position": "AI产品经理",
                "label": "胡泽群 AI产品经理",
                "latest_message": "简历可以下载",
                "unread_count": 1,
                "messages": [{"sender": "other", "text": "简历可以下载"}],
                "online_resume_bytes": b"%PDF-1.7\nnew-watermark\n%%EOF",
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
                    "AI产品经理": {
                        "directResume": True,
                        "resumeRequestPrompt": "请发送简历",
                    }
                },
                "companyKnowledgeBase": {},
            },
            conversation_repository=conversation_repo,
            artifact_store=artifact_store,
        ).run_current()
    )

    assert state["stage"] == "resume_already_downloaded"
    assert page.resume_requests == 0
    artifact = artifact_store.find_business_download(
        session_id=old_session.id,
        platform=Platform.JOB51.value,
        owner="owner",
        platform_conversation_id="old-platform-conversation",
        position="AI产品经理",
    )
    assert artifact is not None
    assert artifact.parse_status == "parsed"
    assert ResumeRepository(database).get(artifact.resume_id) is not None


def test_runner_skips_business_actions_for_completed_canonical_message_snapshot(
    tmp_path: Path,
) -> None:
    database = tmp_path / "canonical-snapshot-guard.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    bootstrap = Conversation(
        id="snapshot-guard",
        platform=Platform.JOB51,
        owner="owner",
        candidate=Candidate(name="Candidate", applied_position="DirectRole"),
        messages=[ChatMessage(sender=MessageSender.CANDIDATE, text="简历可以下载")],
        should_reply=True,
    )
    session = resolve_or_create_session(conversation_repo, bootstrap).session
    conversation_repo.update_session_progress(
        session.id,
        current_stage="download_not_captured",
        next_action="request_resume_failed",
    )
    conversation_repo.save_status(
        CandidateStatus(
            session_id=session.id,
            last_action="request_resume_failed",
            decided_result="download_not_captured",
            payload={
                "lastDecision": {
                    "action": "request_resume_failed",
                    "reason": "download_not_captured",
                }
            },
        )
    )
    fingerprint = recent_messages_fingerprint(bootstrap.messages)
    agent_manager.record_processing_snapshot(
        database,
        owner="owner",
        platform=Platform.JOB51.value,
        summary={
            "processed": 1,
            "selectedProcessingKey": "old-list-key",
            "provisionalProcessingKey": "old-list-key",
            "canonicalProcessingKey": f"session|{session.id}|message|{fingerprint}",
            "canonicalSessionId": session.id,
            "latestMessageFingerprint": fingerprint,
            "nextAction": "request_resume",
            "stage": "resume_attachment_downloaded",
        },
        classification=agent_manager.Classification(False, []),
    )
    page = FakePage(
        conversations=[
            {
                "id": "snapshot-guard",
                "name": "Candidate",
                "position": "DirectRole",
                "label": "Candidate DirectRole",
                "latest_message": "简历可以下载",
                "unread_count": 1,
                "messages": [{"sender": "other", "text": "简历可以下载"}],
                "online_resume_bytes": b"%PDF-1.7\nnew-watermark\n%%EOF",
                "online_resume_filename": "candidate.pdf",
            }
        ]
    )
    adapter = Job51Adapter(page, owner="owner", dry_run=False)
    sink = InMemoryDecisionSink()

    state = asyncio.run(
        ConversationRunner(
            adapter,
            rules={
                "positionReplies": {
                    "DirectRole": {
                        "directResume": True,
                        "resumeRequestPrompt": "请发送简历",
                    }
                },
                "companyKnowledgeBase": {},
            },
            decision_sink=sink,
            conversation_repository=conversation_repo,
            artifact_store=artifact_store,
        ).run_current()
    )

    assert state["stage"] == "message_snapshot_already_processed"
    assert page.resume_requests == 0
    assert artifact_store.list_pending() == []
    persisted_session = conversation_repo.get_session(session.id)
    persisted_status = conversation_repo.get_status(session.id)
    assert persisted_session is not None
    assert persisted_session.current_stage == "download_not_captured"
    assert persisted_session.next_action == "request_resume_failed"
    assert persisted_status.last_action == "request_resume_failed"
    assert persisted_status.decided_result == "download_not_captured"
    assert persisted_status.payload["lastDecision"] == {
        "action": "request_resume_failed",
        "reason": "download_not_captured",
    }
    assert sink.events == []


def test_runner_persists_and_parses_artifact_after_live_download(tmp_path: Path) -> None:
    """51job 真实下载后立即解析当前 artifact 并写入关联简历。"""

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
    artifact = artifact_store.find_business_download(
        session_id=session.id,
        platform=session.platform,
        owner=session.owner,
        platform_conversation_id=session.platform_conversation_id,
        position=session.position,
    )
    assert state["next_action"] == "request_resume"
    assert session is not None
    assert session.current_stage == "resume_attachment_downloaded"
    assert status.resume_downloaded is True
    assert status.resume_path
    assert artifact is not None
    assert artifact.parse_status == "parsed"
    resume = ResumeRepository(database).get(artifact.resume_id)
    assert resume is not None
    assert resume.linked_session_id == session.id
    assert resume.source_artifact_id == artifact.id


def test_runner_uses_rule_resume_job_type_for_truncated_fullstack_download(
    tmp_path: Path,
) -> None:
    """平台截断岗位名时，下载入库仍应使用规则中的全栈岗位并立即评分。"""

    database = tmp_path / "fullstack-download.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    truncated_position = "平台岗位显示...Owner"
    page = FakePage(
        conversations=[
            {
                "id": "job51-fullstack",
                "name": "Dana",
                "position": truncated_position,
                "label": f"Dana {truncated_position}",
                "latest_message": "对方向你发送了简历",
                "unread_count": 1,
                "messages": [{"sender": "other", "text": "对方向你发送了简历"}],
                "online_resume_bytes": (
                    b"%PDF-1.7\n8 years TypeScript React Next.js Node.js SQL API "
                    b"mini program Taro WeCom OAuth JS-SDK OpenFGA CI/CD Agent RAG "
                    b"Tech Lead engineering owner\n%%EOF"
                ),
                "online_resume_filename": "Dana_fullstack.pdf",
            }
        ]
    )
    adapter = Job51Adapter(page, owner="和新红", dry_run=False)

    state = asyncio.run(
        ConversationRunner(
            adapter,
            rules={
                "positionReplies": {
                    truncated_position: {
                        "directResume": True,
                        "resumeJobType": "全栈工程师",
                        "resumeRequestPrompt": "你好，可以看看简历吗",
                    }
                },
                "companyKnowledgeBase": {},
            },
            conversation_repository=conversation_repo,
            artifact_store=artifact_store,
        ).run_current()
    )

    session = conversation_repo.get_session(str(state["session_id"]))
    assert session is not None
    artifact = artifact_store.find_business_download(
        session_id=session.id,
        platform=session.platform,
        owner=session.owner,
        platform_conversation_id=session.platform_conversation_id,
        position=session.position,
    )
    assert artifact is not None
    assert artifact.position == "全栈工程师"
    resume = ResumeRepository(database).get(artifact.resume_id)
    assert resume is not None
    assert resume.job_type == "全栈工程师"
    assert resume.payload["applied_position"] == "全栈工程师"
    assert resume.match_score is not None


def test_zhilian_uses_rule_resume_job_type_for_fullstack_download(tmp_path: Path) -> None:
    """智联附件下载也应使用规则中的规范岗位并立即评分。"""

    database = tmp_path / "zhilian-fullstack-download.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    platform_position = "智联展示岗位...Owner"
    page = FakePage(
        conversations=[
            {
                "id": "zhilian-fullstack",
                "name": "Evan",
                "position": platform_position,
                "label": f"Evan {platform_position}",
                "latest_message": "您好，附件是我的简历",
                "unread_count": 1,
                "messages": [{"sender": "other", "text": "您好，附件是我的简历"}],
                "has_resume_attachment": True,
                "resume_bytes": (
                    b"%PDF-1.7\nTypeScript React Next.js Node.js SQL API mini program "
                    b"Taro WeCom JS-SDK OpenFGA Pull Request Code Review CI/CD "
                    b"Agent RAG Eval Tech Lead\n%%EOF"
                ),
                "resume_filename": "Evan_fullstack.pdf",
            }
        ]
    )
    adapter = ZhilianAdapter(page, owner="宋峰峰", dry_run=False)

    state = asyncio.run(
        ConversationRunner(
            adapter,
            rules={
                "positionReplies": {
                    platform_position: {
                        "directResume": True,
                        "resumeJobType": "全栈工程师",
                        "resumeRequestPrompt": "你好，可以看看简历吗",
                    }
                },
                "companyKnowledgeBase": {},
            },
            conversation_repository=conversation_repo,
            artifact_store=artifact_store,
        ).run_current()
    )

    session = conversation_repo.get_session(str(state["session_id"]))
    assert session is not None
    artifact = artifact_store.find_business_download(
        session_id=session.id,
        platform=session.platform,
        owner=session.owner,
        platform_conversation_id=session.platform_conversation_id,
        position=session.position,
    )
    assert artifact is not None
    assert artifact.position == "全栈工程师"
    resume = ResumeRepository(database).get(artifact.resume_id)
    assert resume is not None
    assert resume.job_type == "全栈工程师"
    assert resume.match_score is not None


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
    conversation_repo.save_status(CandidateStatus(session_id=session.id, resume_requested=True))
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
    artifact = artifact_store.find_business_download(
        session_id=session.id,
        platform=session.platform,
        owner=session.owner,
        platform_conversation_id=session.platform_conversation_id,
        position=session.position,
    )
    assert state["next_action"] == "request_resume"
    assert state["stage"] != "resume_already_completed"
    assert state["decision"]["result"]["downloaded"] is True
    assert status.resume_requested is True
    assert status.resume_downloaded is True
    assert artifact is not None
    assert artifact.parse_status == "parsed"


def test_zhilian_attachment_download_is_parsed_and_linked(tmp_path: Path) -> None:
    database = tmp_path / "zhilian-live-download.sqlite"
    conversation_repo = ConversationRepository(database)
    artifact_store = ResumeArtifactStore(database)
    page = FakePage(
        conversations=[
            {
                "id": "zhilian-live-download",
                "name": "平台候选人",
                "position": "外部财务产品顾问",
                "label": "平台候选人 外部财务产品顾问",
                "latest_message": "您好，这是我的附件简历，请查收 查看附件简历",
                "unread_count": 1,
                "messages": [
                    {
                        "sender": "other",
                        "text": "您好，这是我的附件简历，请查收\n查看附件简历",
                    }
                ],
                "has_resume_attachment": True,
                "resume_bytes": b"%PDF-1.7\nName: Alice\nfinance consultant\n%%EOF",
                "resume_filename": "Alice_finance_consultant.pdf",
            }
        ]
    )
    adapter = ZhilianAdapter(page, owner="宋峰峰", dry_run=False)

    state = asyncio.run(
        ConversationRunner(
            adapter,
            rules={
                "positionReplies": {
                    "外部财务产品顾问": {
                        "directResume": True,
                        "resumeRequestPrompt": "请发送简历",
                    }
                },
                "companyKnowledgeBase": {},
            },
            conversation_repository=conversation_repo,
            artifact_store=artifact_store,
        ).run_current()
    )

    session = conversation_repo.get_session(str(state["session_id"]))
    assert session is not None
    artifact = artifact_store.find_business_download(
        session_id=session.id,
        platform=Platform.ZHILIAN.value,
        owner="宋峰峰",
        platform_conversation_id="zhilian-live-download",
        position="外部财务产品顾问",
    )
    assert state["stage"] == "resume_attachment_downloaded"
    assert artifact is not None
    assert artifact.parse_status == "parsed"
    resume = ResumeRepository(database).get(artifact.resume_id)
    assert resume is not None
    assert resume.linked_platform == Platform.ZHILIAN.value
    assert resume.linked_owner == "宋峰峰"
    assert resume.payload["platform"] == Platform.ZHILIAN.value
    assert resume.payload["owner"] == "宋峰峰"
    assert resume.linked_session_id == session.id
    assert resume.linked_platform_conversation_id == "zhilian-live-download"


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
