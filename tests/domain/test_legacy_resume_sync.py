"""Legacy resume database sync tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.db.engine import run_migrations
from scripts.sync_legacy_resumes import SyncConfig, run_sync


def test_legacy_sync_dry_run_does_not_write_target(tmp_path: Path) -> None:
    legacy_db, legacy_uploads = _build_legacy_db(tmp_path, resume_id="resume-1")
    target_db = tmp_path / "target.sqlite"
    target_uploads = tmp_path / "target-uploads"

    report = run_sync(
        SyncConfig(
            legacy_db=legacy_db,
            legacy_upload_dir=legacy_uploads,
            target_db=target_db,
            target_upload_dir=target_uploads,
            apply=False,
        )
    )

    assert report["dryRun"] is True
    assert report["scanned"] == 1
    assert report["wouldImport"] == 1
    assert report["pdfExisting"] == 1
    assert not target_db.exists()
    assert not target_uploads.exists()


def test_legacy_sync_apply_replace_copies_pdf_and_rewrites_payload(
    tmp_path: Path,
) -> None:
    legacy_db, legacy_uploads = _build_legacy_db(tmp_path, resume_id="resume-2")
    target_db = tmp_path / "target.sqlite"
    target_uploads = tmp_path / "target-uploads"
    run_migrations(target_db)
    _insert_target_marker(target_db)

    report = run_sync(
        SyncConfig(
            legacy_db=legacy_db,
            legacy_upload_dir=legacy_uploads,
            target_db=target_db,
            target_upload_dir=target_uploads,
            mode="replace",
            apply=True,
            yes=True,
        )
    )

    assert report["dryRun"] is False
    assert report["imported"] == 1
    assert report["replacedTarget"] is True
    assert report["targetBackupPath"]

    with sqlite3.connect(target_db) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM resumes ORDER BY id").fetchall()
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]

    assert quick_check == "ok"
    assert [row["id"] for row in rows] == ["resume-2"]
    payload = json.loads(rows[0]["payload"])
    copied_pdf = Path(payload["pdfPath"])
    assert copied_pdf == target_uploads / "legacy" / "resume-2.pdf"
    assert copied_pdf.read_bytes() == b"%PDF-1.4\nlegacy-pdf\n"
    assert payload["legacyPdfPath"].endswith("resume-2.pdf")
    assert rows[0]["parsed_name"] == "Alice"
    assert rows[0]["linked_session_id"] in ("", None)


def test_legacy_sync_merge_skips_existing_resume(tmp_path: Path) -> None:
    legacy_db, legacy_uploads = _build_legacy_db(tmp_path, resume_id="resume-3")
    target_db = tmp_path / "target.sqlite"
    target_uploads = tmp_path / "target-uploads"
    run_migrations(target_db)
    _insert_existing_resume(target_db, "resume-3")

    report = run_sync(
        SyncConfig(
            legacy_db=legacy_db,
            legacy_upload_dir=legacy_uploads,
            target_db=target_db,
            target_upload_dir=target_uploads,
            mode="merge",
            apply=True,
            yes=True,
        )
    )

    assert report["imported"] == 0
    assert report["skippedExisting"] == 1

    with sqlite3.connect(target_db) as connection:
        payload = connection.execute(
            "SELECT payload FROM resumes WHERE id = ?",
            ("resume-3",),
        ).fetchone()[0]
    assert json.loads(payload)["name"] == "Existing"


def _build_legacy_db(tmp_path: Path, *, resume_id: str) -> tuple[Path, Path]:
    legacy_uploads = tmp_path / "legacy-uploads"
    legacy_uploads.mkdir()
    pdf_path = legacy_uploads / f"{resume_id}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nlegacy-pdf\n")
    legacy_db = tmp_path / "legacy.sqlite"
    with sqlite3.connect(legacy_db) as connection:
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
        payload = {
            "id": resume_id,
            "name": "Alice",
            "jobType": "AI应用开发实习生",
            "platform": "boss",
            "accountName": "宋峰峰",
            "pdfPath": str(pdf_path),
        }
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
                "13800138000",
                "AI应用开发实习生",
                88,
                "2026-06-01T00:00:00",
            ),
        )
        connection.commit()
    return legacy_db, legacy_uploads


def _insert_target_marker(target_db: Path) -> None:
    _insert_existing_resume(target_db, "old-target")


def _insert_existing_resume(target_db: Path, resume_id: str) -> None:
    with sqlite3.connect(target_db) as connection:
        connection.execute(
            """
            INSERT INTO resumes (
              id, payload, phone_key, job_type, match_score, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                resume_id,
                json.dumps({"name": "Existing"}, ensure_ascii=False),
                "",
                "旧岗位",
                1,
                "2026-01-01T00:00:00",
            ),
        )
        connection.commit()
