from __future__ import annotations

import json
from pathlib import Path

from app.core.constants import Platform
from app.db.engine import connect, run_migrations
from app.domain.conversation.identity import resolve_or_create_session
from app.domain.conversation.repository import ConversationRepository
from app.platforms.types import Candidate, Conversation
from scripts.backfill_fullstack_resume_artifacts import backfill_fullstack_resume_artifacts


def test_backfill_repairs_parsed_fullstack_artifact_and_missing_score(tmp_path: Path) -> None:
    database = tmp_path / "resumes.sqlite"
    run_migrations(database)
    raw_position = "资深全栈工程...程 Owner）"
    payload = {
        "name": "Dana",
        "applied_position": raw_position,
        "rawText": (
            "8年 TypeScript React Next.js Node.js SQL API 微信小程序 Taro "
            "企业微信 WeCom JS-SDK 多租户 OpenFGA Pull Request Code Review "
            "自动化测试 CI/CD UAT Agent RAG Eval Tech Lead 带领团队"
        ),
    }
    session = resolve_or_create_session(
        ConversationRepository(database),
        Conversation(
            id="platform-fullstack-old",
            platform=Platform.JOB51,
            owner="和新红",
            candidate=Candidate(name="Dana", applied_position=raw_position),
            messages=[],
            should_reply=False,
        ),
    ).session
    with connect(database) as connection:
        connection.execute(
            """
            INSERT INTO resume_artifacts (
              id, session_id, platform, owner, platform_conversation_id,
              candidate_name_from_platform, position, file_path, file_hash,
              source_kind, parse_status, parsed_name, resume_id, error,
              created_at, updated_at
            ) VALUES (?, ?, 'job51', ?, ?, ?, ?, ?, ?, 'online_resume',
                      'pending', '', '', '', ?, ?)
            """,
            (
                "artifact-fullstack-old",
                session.id,
                session.owner,
                session.platform_conversation_id,
                "Dana",
                raw_position,
                str(tmp_path / "Dana.pdf"),
                "hash-fullstack-old",
                "2026-07-21T00:00:00+00:00",
                "2026-07-21T00:00:00+00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO resumes (
              id, payload, phone_key, job_type, match_score, updated_at,
              parsed_name, linked_session_id, linked_platform, linked_owner,
              linked_platform_conversation_id, source_artifact_id
            ) VALUES (?, ?, '', ?, NULL, ?, ?, ?, 'job51', ?, ?, ?)
            """,
            (
                "resume-fullstack-old",
                json.dumps(payload, ensure_ascii=False),
                raw_position,
                "2026-07-21T00:00:00+00:00",
                "Dana",
                session.id,
                session.owner,
                session.platform_conversation_id,
                "artifact-fullstack-old",
            ),
        )
        connection.execute(
            """
            UPDATE resume_artifacts
            SET parse_status = 'parsed', parsed_name = ?, resume_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                "Dana",
                "resume-fullstack-old",
                "2026-07-21T00:00:00+00:00",
                "artifact-fullstack-old",
            ),
        )
        connection.commit()

    dry_run = backfill_fullstack_resume_artifacts(database, apply=False)
    assert dry_run["candidates"] == 1
    assert dry_run["repaired"] == 0

    backup_dir = tmp_path / "backups"
    applied = backfill_fullstack_resume_artifacts(
        database,
        apply=True,
        backup_dir=backup_dir,
    )
    assert applied["candidates"] == 1
    assert applied["repaired"] == 1
    assert Path(applied["backupPath"]).exists()

    with connect(database, read_only=True) as connection:
        artifact = connection.execute(
            "SELECT position FROM resume_artifacts WHERE id = ?",
            ("artifact-fullstack-old",),
        ).fetchone()
        resume = connection.execute(
            "SELECT payload, job_type, match_score FROM resumes WHERE id = ?",
            ("resume-fullstack-old",),
        ).fetchone()

    assert artifact["position"] == "全栈工程师"
    assert resume["job_type"] == "全栈工程师"
    assert resume["match_score"] >= 75
    assert json.loads(resume["payload"])["applied_position"] == "全栈工程师"
