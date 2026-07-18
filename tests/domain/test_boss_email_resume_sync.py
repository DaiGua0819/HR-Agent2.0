"""BOSS email resume sync tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.db.engine import run_migrations
from app.domain.conversation.models import ConversationSession
from app.domain.conversation.repository import ConversationRepository
from app.platforms.types import ChatMessage, MessageSender
from scripts.sync_boss_email_resumes import (
    BossEmailSyncConfig,
    infer_boss_email_job_type,
    run_sync,
)


def test_infer_boss_email_job_type_uses_noisy_original_position() -> None:
    assert (
        infer_boss_email_job_type(
            {"fileName": "mail_【AI_产品经_理_杭州_20_-40K】Candidate.pdf"}
        )
        == "AI产品经理"
    )
    assert (
        infer_boss_email_job_type(
            {"fileName": "mail_【AI智_能体解决方_案负责人_上海_4_0-60K】A.pdf"}
        )
        == "AI智能体解决方案负责人"
    )
    assert (
        infer_boss_email_job_type(
            {"fileName": "mail_【企业内容运营负责人_（B2B_短视频方向）】A.pdf"}
        )
        == "运营A"
    )


def test_boss_email_sync_dry_run_does_not_write_target(tmp_path: Path) -> None:
    source_db, source_uploads = _build_source_db(tmp_path)
    target_db = tmp_path / "target.sqlite"
    target_uploads = tmp_path / "target-uploads"

    report = run_sync(
        BossEmailSyncConfig(
            source_db=source_db,
            source_upload_dir=source_uploads,
            target_db=target_db,
            target_upload_dir=target_uploads,
        ),
        now_iso="2026-07-13T08:00:00+00:00",
    )

    assert report["dryRun"] is True
    assert report["sourceBoss"] == 1
    assert report["wouldImport"] == 1
    assert report["skippedNonBoss"] == 1
    assert report["pdfExisting"] == 1
    assert not target_db.exists()
    assert not target_uploads.exists()


def test_boss_email_sync_imports_only_missing_boss_resume_with_current_time(
    tmp_path: Path,
) -> None:
    source_db, source_uploads = _build_source_db(tmp_path)
    target_db = tmp_path / "target.sqlite"
    target_uploads = tmp_path / "target-uploads"
    run_migrations(target_db)

    report = run_sync(
        BossEmailSyncConfig(
            source_db=source_db,
            source_upload_dir=source_uploads,
            target_db=target_db,
            target_upload_dir=target_uploads,
            apply=True,
            yes=True,
        ),
        now_iso="2026-07-13T08:00:00+00:00",
    )

    assert report["imported"] == 1
    assert report["pdfCopied"] == 1

    with sqlite3.connect(target_db) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM resumes ORDER BY id").fetchall()

    assert [row["id"] for row in rows] == ["boss-resume"]
    row = rows[0]
    assert row["updated_at"] == "2026-07-13T08:00:00+00:00"
    assert row["job_type"] == "AI产品经理"
    assert row["linked_platform"] == "boss"
    assert row["linked_owner"] == "Boss Owner"
    payload = json.loads(row["payload"])
    assert payload["jobType"] == "AI产品经理"
    assert payload["bossEmailOriginalJobType"] == "Test Job"
    assert payload["bossEmailPositionEvidence"].startswith("AI_产品经_理")
    copied_pdf = target_uploads / "boss-email" / "boss-resume.pdf"
    assert Path(payload["pdfPath"]) == copied_pdf
    assert Path(payload["filePath"]) == copied_pdf
    assert copied_pdf.read_bytes() == b"%PDF-1.4\nboss-resume\n"


def test_boss_email_sync_links_unique_candidate_conversation(tmp_path: Path) -> None:
    source_db, source_uploads = _build_source_db(tmp_path)
    target_db = tmp_path / "target.sqlite"
    target_uploads = tmp_path / "target-uploads"
    run_migrations(target_db)
    target_job = infer_boss_email_job_type(
        {"fileName": "mail_【AI_产品经理_杭州_20_-40K】Candidate.pdf"}
    )
    conversation_repository = ConversationRepository(target_db)
    conversation_repository.save_session(
        ConversationSession(
            id="boss-session",
            platform="boss",
            owner="Boss Owner",
            candidate_name="Candidate",
            position=target_job,
            platform_conversation_id="boss-conversation",
        )
    )
    conversation_repository.upsert_messages(
        "boss-session",
        [ChatMessage(sender=MessageSender.CANDIDATE, text="resume accepted")],
    )

    report = run_sync(
        BossEmailSyncConfig(
            source_db=source_db,
            source_upload_dir=source_uploads,
            target_db=target_db,
            target_upload_dir=target_uploads,
            apply=True,
            yes=True,
        ),
        now_iso="2026-07-13T08:00:00+00:00",
    )

    with sqlite3.connect(target_db) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM resumes WHERE id = ?", ("boss-resume",)
        ).fetchone()

    assert report["linkedUnique"] == 1
    assert row["linked_session_id"] == "boss-session"
    assert row["linked_platform"] == "boss"
    assert row["linked_owner"] == "Boss Owner"
    assert row["linked_platform_conversation_id"] == "boss-conversation"


def test_boss_email_sync_skips_existing_target_resume(tmp_path: Path) -> None:
    source_db, source_uploads = _build_source_db(tmp_path)
    target_db = tmp_path / "target.sqlite"
    target_uploads = tmp_path / "target-uploads"
    run_migrations(target_db)
    _insert_existing_target(target_db, "boss-resume")

    report = run_sync(
        BossEmailSyncConfig(
            source_db=source_db,
            source_upload_dir=source_uploads,
            target_db=target_db,
            target_upload_dir=target_uploads,
            apply=True,
            yes=True,
        )
    )

    assert report["wouldImport"] == 0
    assert report["imported"] == 0
    assert report["skippedExisting"] == 1


def test_boss_email_sync_repairs_previously_synced_job_type(tmp_path: Path) -> None:
    source_db, source_uploads = _build_source_db(tmp_path)
    target_db = tmp_path / "target.sqlite"
    target_uploads = tmp_path / "target-uploads"
    run_migrations(target_db)
    _insert_existing_target(target_db, "boss-resume", synced=True)

    report = run_sync(
        BossEmailSyncConfig(
            source_db=source_db,
            source_upload_dir=source_uploads,
            target_db=target_db,
            target_upload_dir=target_uploads,
            repair_existing=True,
            apply=True,
            yes=True,
        ),
        now_iso="2026-07-13T09:00:00+00:00",
    )

    assert report["wouldRepair"] == 1
    assert report["repaired"] == 1

    with sqlite3.connect(target_db) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM resumes WHERE id = ?", ("boss-resume",)
        ).fetchone()

    assert row["job_type"] == "AI产品经理"
    assert row["updated_at"] == "2026-07-13T09:00:00+00:00"
    payload = json.loads(row["payload"])
    assert payload["jobType"] == "AI产品经理"
    assert payload["bossEmailOriginalJobType"] == "Existing Job"
    assert payload["bossEmailJobCorrectedAt"] == "2026-07-13T09:00:00+00:00"


def _build_source_db(tmp_path: Path) -> tuple[Path, Path]:
    source_uploads = tmp_path / "source-uploads"
    source_uploads.mkdir()
    boss_pdf = source_uploads / "boss-resume.pdf"
    boss_pdf.write_bytes(b"%PDF-1.4\nboss-resume\n")
    other_pdf = source_uploads / "other-resume.pdf"
    other_pdf.write_bytes(b"%PDF-1.4\nother-resume\n")
    source_db = tmp_path / "source.sqlite"
    with sqlite3.connect(source_db) as connection:
        connection.execute(
            """
            CREATE TABLE resumes (
              id TEXT PRIMARY KEY,
              payload TEXT NOT NULL,
              phone_key TEXT,
              job_type TEXT,
              match_score INTEGER,
              updated_at TEXT NOT NULL
            )
            """
        )
        _insert_source_resume(
            connection,
            resume_id="boss-resume",
            platform="boss",
            owner="Boss Owner",
            pdf_path=boss_pdf,
        )
        _insert_source_resume(
            connection,
            resume_id="other-resume",
            platform="zhilian",
            owner="Other Owner",
            pdf_path=other_pdf,
        )
        connection.commit()
    return source_db, source_uploads


def _insert_source_resume(
    connection: sqlite3.Connection,
    *,
    resume_id: str,
    platform: str,
    owner: str,
    pdf_path: Path,
) -> None:
    payload = {
        "id": resume_id,
        "name": "Candidate",
        "platform": platform,
        "accountName": owner,
        "pdfPath": str(pdf_path),
        "filePath": str(pdf_path),
    }
    if platform == "boss":
        payload["fileName"] = "mail_【AI_产品经_理_杭州_20_-40K】Candidate.pdf"
    connection.execute(
        """
        INSERT INTO resumes (id, payload, phone_key, job_type, match_score, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            resume_id,
            json.dumps(payload),
            f"phone-{resume_id}",
            "Test Job",
            88,
            "2026-07-01T00:00:00+00:00",
        ),
    )


def _insert_existing_target(
    target_db: Path,
    resume_id: str,
    *,
    synced: bool = False,
) -> None:
    payload = {"name": "Existing"}
    if synced:
        payload["bossEmailSyncedAt"] = "2026-07-13T08:00:00+00:00"
    with sqlite3.connect(target_db) as connection:
        connection.execute(
            """
            INSERT INTO resumes (id, payload, phone_key, job_type, match_score, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                resume_id,
                json.dumps(payload),
                "existing-phone",
                "Existing Job",
                1,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()
