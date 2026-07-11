from __future__ import annotations

from pathlib import Path

from app.db.engine import connect, run_migrations
from app.domain.resume_review.repository import ResumeReviewRepository
from scripts.backfill_resume_reviewer_names import backfill_reviewer_names


def _database(tmp_path: Path) -> Path:
    database = tmp_path / "resumes.sqlite"
    run_migrations(database)
    repository = ResumeReviewRepository(database)
    repository.upsert_state(
        resume_id="resume-1",
        user_id="feishu:member-a",
        decision="suitable",
    )
    repository.upsert_state(
        resume_id="resume-2",
        user_id="feishu:member-b",
        user_name="已有姓名",
        decision="unsuitable",
    )
    repository.upsert_state(
        resume_id="resume-3",
        user_id="unknown-user",
        decision="suitable",
    )
    return database


def _name(database: Path, user_id: str) -> str:
    with connect(database, read_only=True) as connection:
        row = connection.execute(
            "SELECT user_name FROM resume_review_states WHERE user_id = ? LIMIT 1",
            (user_id,),
        ).fetchone()
    assert row is not None
    return str(row["user_name"])


def test_reviewer_name_backfill_is_dry_run_by_default(tmp_path: Path) -> None:
    database = _database(tmp_path)

    report = backfill_reviewer_names(
        database,
        identities={"feishu:member-a": "成员甲"},
    )

    assert report["apply"] is False
    assert report["matchedRows"] == 1
    assert report["updatedRows"] == 0
    assert report["unresolvedUserIds"] == ["unknown-user"]
    assert _name(database, "feishu:member-a") == ""


def test_reviewer_name_backfill_updates_only_blank_names(tmp_path: Path) -> None:
    database = _database(tmp_path)

    report = backfill_reviewer_names(
        database,
        identities={
            "feishu:member-a": "成员甲",
            "feishu:member-b": "错误覆盖名",
        },
        apply=True,
    )

    assert report["apply"] is True
    assert report["matchedRows"] == 1
    assert report["updatedRows"] == 1
    assert report["preservedNamedRows"] == 1
    assert report["unresolvedUserIds"] == ["unknown-user"]
    assert _name(database, "feishu:member-a") == "成员甲"
    assert _name(database, "feishu:member-b") == "已有姓名"


def test_reviewer_name_backfill_reports_mapping_counts(tmp_path: Path) -> None:
    database = _database(tmp_path)

    report = backfill_reviewer_names(
        database,
        identities={"feishu:member-a": "成员甲", "missing-user": "无人"},
    )

    assert report["identityCounts"] == {
        "feishu:member-a": {"name": "成员甲", "blankRows": 1, "namedRows": 0},
        "missing-user": {"name": "无人", "blankRows": 0, "namedRows": 0},
    }


def test_reviewer_name_backfill_ignores_viewed_only_states(tmp_path: Path) -> None:
    database = _database(tmp_path)
    repository = ResumeReviewRepository(database)
    repository.upsert_state(
        resume_id="resume-4",
        user_id="viewer-only",
        read_status="viewed",
    )

    report = backfill_reviewer_names(
        database,
        identities={"viewer-only": "只查看用户"},
        apply=True,
    )

    assert report["matchedRows"] == 0
    assert report["updatedRows"] == 0
    assert report["identityCounts"]["viewer-only"]["blankRows"] == 0
    assert _name(database, "viewer-only") == ""
