"""Operation resume rescore script tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.db.engine import run_migrations
from app.domain.resume.repository import ResumeRepository
from scripts.rescore_operation_resumes import RescoreConfig, rescore_operation_resumes


def test_operation_rescore_since_date_updates_only_operation_resumes(tmp_path: Path) -> None:
    """The 6.25 rescore should update only operation A/B resumes in the date window."""

    database = tmp_path / "operation_rescore.sqlite"
    run_migrations(database)
    _insert_legacy_resume(
        database,
        "a-new",
        "运营A",
        "2026-06-25T09:00:00",
        "本科 3年短视频内容运营 企业号 账号定位 月度选题 脚本 数据复盘 私信量 有效咨询量 SaaS AI",
    )
    _insert_legacy_resume(
        database,
        "b-new",
        "运营B",
        "2026-06-30T09:00:00",
        "大专 新媒体运营 B2B 工业品 膨润土 钻井泥浆 猫砂 LinkedIn 英文文案 询盘 有效线索",
    )
    _insert_legacy_resume(database, "a-old", "运营A", "2026-06-24T23:59:59", "本科 企业号")
    _insert_legacy_resume(database, "other", "电气工程师", "2026-06-30T09:00:00", "本科 PLC")
    repository = ResumeRepository(database)

    dry_run = rescore_operation_resumes(
        RescoreConfig(database_path=database, since="2026-06-25", apply=False)
    )
    assert dry_run["dryRun"] is True
    assert dry_run["matched"] == 2
    assert dry_run["updated"] == 0
    assert repository.get("a-new").match_score is None

    applied = rescore_operation_resumes(
        RescoreConfig(database_path=database, since="2026-06-25", apply=True)
    )

    assert applied["dryRun"] is False
    assert applied["matched"] == 2
    assert applied["updated"] == 2
    assert repository.get("a-new").match_score >= 75
    assert repository.get("b-new").match_score >= 75
    assert repository.get("a-old").match_score is None
    assert repository.get("other").match_score is None


def _insert_legacy_resume(
    database: Path,
    resume_id: str,
    job_type: str,
    updated_at: str,
    raw_text: str,
) -> None:
    payload = {"name": resume_id, "jobType": job_type, "rawText": raw_text}
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO resumes (
              id, payload, phone_key, job_type, match_score, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                resume_id,
                json.dumps(payload, ensure_ascii=False),
                "",
                job_type,
                None,
                updated_at,
            ),
        )
        connection.commit()
