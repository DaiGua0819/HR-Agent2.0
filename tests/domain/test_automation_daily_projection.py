from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from app.db.engine import run_migrations
from app.domain.automation_monitoring.daily_projection import build_daily_projections


def test_projection_keeps_latest_result_and_accumulates_daily_flags(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    _insert_session(database, session_id="session-1", updated_at="2026-07-20T02:00:00+00:00")
    runs = tmp_path / "runs"
    _write_run(
        runs,
        [
            _contact_result(
                timestamp="2026-07-20T01:00:00+00:00",
                session_id="session-1",
                action="request_resume",
                stage="resume_requested",
                resume_handling="resume_requested_waiting",
            ),
            _contact_result(
                timestamp="2026-07-20T02:00:00+00:00",
                session_id="session-1",
                action="answer_question",
                stage="knowledge_hit",
            ),
        ],
    )

    exported = build_daily_projections(
        database_path=database,
        run_dir=runs,
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 20),
    )

    assert len(exported.events) == 1
    event = exported.events[0]
    assert event.id.startswith("automation-daily-2026-07-20-")
    assert event.contact_key == "session|session-1"
    assert event.action == "answer_question"
    assert event.stage == "knowledge_hit"
    assert event.occurred_at == "2026-07-20T02:00:00+00:00"
    assert event.requested_resume is True
    assert event.candidate_question is True
    assert event.knowledge_answered is True
    assert event.candidate_name == "张三"
    assert event.job_type == "AI产品经理"
    assert exported.coverage["managerContactResults"] == 2
    assert exported.coverage["exactCandidates"] == 1


def test_projection_uses_session_fallback_when_manager_run_is_missing(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    _insert_session(
        database,
        session_id="session-fallback",
        platform="zhilian",
        owner="宋峰峰",
        candidate_name="李四",
        job_type="运营B",
        next_action="ask_screening",
        stage="screening_question_sent",
        updated_at="2026-07-14T04:00:00+00:00",
    )

    exported = build_daily_projections(
        database_path=database,
        run_dir=tmp_path / "missing-runs",
        start_date=date(2026, 7, 14),
        end_date=date(2026, 7, 14),
    )

    assert len(exported.events) == 1
    event = exported.events[0]
    assert event.contact_key == "session|session-fallback"
    assert event.action == "ask_screening"
    assert event.sent_company_info is True
    assert event.owner == "宋峰峰"
    assert event.platform == "zhilian"
    assert exported.coverage["fallbackCandidates"] == 1


def test_projection_resolves_legacy_manager_conversation_to_session(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    _insert_session(
        database,
        session_id="legacy-session",
        updated_at="2026-07-20T02:00:00+00:00",
    )
    record = _contact_result(
        timestamp="2026-07-20T02:00:00+00:00",
        session_id="legacy-session",
        action="request_resume",
        stage="resume_requested",
    )
    record["summary"].pop("canonicalSessionId")
    record["response"].pop("canonicalSessionId")
    record["summary"]["conversationId"] = "platform-legacy-session"
    record["response"]["conversationId"] = "platform-legacy-session"
    runs = tmp_path / "runs"
    _write_run(runs, [record])

    exported = build_daily_projections(
        database_path=database,
        run_dir=runs,
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 20),
    )

    assert len(exported.events) == 1
    assert exported.events[0].contact_key == "session|legacy-session"
    assert exported.coverage["exactCandidates"] == 1
    assert exported.coverage["fallbackCandidates"] == 0


def test_projection_keeps_same_candidate_separate_across_days(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_session(database, session_id="session-2", updated_at="2026-07-20T01:00:00+00:00")
    runs = tmp_path / "runs"
    _write_run(
        runs,
        [
            _contact_result(
                timestamp="2026-07-19T01:00:00+00:00",
                session_id="session-2",
                action="ask_basic_conditions",
                stage="basic_conditions_sent",
            ),
            _contact_result(
                timestamp="2026-07-20T01:00:00+00:00",
                session_id="session-2",
                action="request_resume",
                stage="resume_requested",
            ),
        ],
    )

    exported = build_daily_projections(
        database_path=database,
        run_dir=runs,
        start_date=date(2026, 7, 19),
        end_date=date(2026, 7, 20),
    )

    assert len(exported.events) == 2
    assert {tuple(event.id.split("-")[2:5]) for event in exported.events} == {
        ("2026", "07", "19"),
        ("2026", "07", "20"),
    }


def test_projection_maps_resume_acquisition_and_anomaly(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_session(
        database,
        session_id="boss-session",
        platform="boss",
        owner="和新红",
        updated_at="2026-07-20T01:00:00+00:00",
    )
    _insert_session(
        database,
        session_id="job51-session",
        platform="job51",
        owner="宋峰峰",
        updated_at="2026-07-20T02:00:00+00:00",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO resume_artifacts (
              id, session_id, platform, owner, platform_conversation_id,
              candidate_name_from_platform, position, file_path, file_hash,
              source_kind, parse_status, parsed_name, resume_id, error,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'parsed', ?, ?, '', ?, ?)
            """,
            (
                "artifact-1",
                "job51-session",
                "job51",
                "宋峰峰",
                "platform-job51-session",
                "张三",
                "AI产品经理",
                "C:/resumes/job51.pdf",
                "file-hash-1",
                "attachment",
                "张三",
                "resume-1",
                "2026-07-20T02:00:00+00:00",
                "2026-07-20T02:00:00+00:00",
            ),
        )
        connection.commit()
    runs = tmp_path / "runs"
    _write_run(
        runs,
        [
            _contact_result(
                timestamp="2026-07-20T01:00:00+00:00",
                session_id="boss-session",
                owner="和新红",
                platform="boss",
                action="request_resume",
                stage="request_confirmed",
                resume_handling="boss_request_verified_server_imap",
            ),
            _contact_result(
                timestamp="2026-07-20T02:00:00+00:00",
                session_id="job51-session",
                owner="宋峰峰",
                platform="job51",
                action="request_resume_failed",
                stage="download_error",
                anomaly=True,
                anomaly_reasons=["download_error"],
            ),
        ],
    )

    exported = build_daily_projections(
        database_path=database,
        run_dir=runs,
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 20),
    )
    by_session = {event.contact_key: event for event in exported.events}

    assert by_session["session|boss-session"].resume_acquired is True
    assert (
        by_session["session|boss-session"].resume_handling
        == "boss_request_verified_server_imap"
    )
    assert by_session["session|job51-session"].resume_acquired is True
    assert by_session["session|job51-session"].resume_file_hash == "file-hash-1"
    assert by_session["session|job51-session"].anomaly is True
    assert by_session["session|job51-session"].anomaly_reason == "download_error"


def test_projection_summary_dedupes_local_resume_hashes(tmp_path: Path) -> None:
    database = _database(tmp_path)
    for session_id in ("session-a", "session-b"):
        _insert_session(
            database,
            session_id=session_id,
            updated_at="2026-07-20T02:00:00+00:00",
        )
    with sqlite3.connect(database) as connection:
        for index, session_id in enumerate(("session-a", "session-b"), start=1):
            connection.execute(
                """
                INSERT INTO resume_artifacts (
                  id, session_id, platform, owner, platform_conversation_id,
                  candidate_name_from_platform, position, file_path, file_hash,
                  source_kind, parse_status, parsed_name, resume_id, error,
                  created_at, updated_at
                ) VALUES (?, ?, 'job51', '和新红', ?, '张三', 'AI产品经理',
                          ?, 'shared-file-hash', 'attachment', 'parsed', '张三',
                          ?, '', ?, ?)
                """,
                (
                    f"artifact-{index}",
                    session_id,
                    f"platform-{session_id}",
                    f"C:/resumes/{index}.pdf",
                    f"resume-{index}",
                    "2026-07-20T02:00:00+00:00",
                    "2026-07-20T02:00:00+00:00",
                ),
            )
        connection.commit()

    exported = build_daily_projections(
        database_path=database,
        run_dir=tmp_path / "missing-runs",
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 20),
    )

    assert len(exported.events) == 2
    assert exported.summary["byDate"]["2026-07-20"][
        "businessResumeAcquisitions"
    ] == 1


def _database(tmp_path: Path) -> Path:
    database = tmp_path / "resumes.sqlite"
    run_migrations(database)
    return database


def _insert_session(
    database: Path,
    *,
    session_id: str,
    platform: str = "job51",
    owner: str = "和新红",
    candidate_name: str = "张三",
    job_type: str = "AI产品经理",
    next_action: str = "wait",
    stage: str = "waiting",
    updated_at: str,
) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO conversation_sessions (
              id, platform, owner, candidate_name, position, applied_position,
              platform_conversation_id, label, current_stage, next_action,
              recent_messages_fingerprint, identity_confidence,
              identity_warnings, last_seen_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, '', 'high', '[]', ?, ?, ?)
            """,
            (
                session_id,
                platform,
                owner,
                candidate_name,
                job_type,
                job_type,
                f"platform-{session_id}",
                stage,
                next_action,
                updated_at,
                updated_at,
                updated_at,
            ),
        )
        connection.commit()


def _write_run(run_dir: Path, events: list[dict[str, object]]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n",
        encoding="utf-8",
    )


def _contact_result(
    *,
    timestamp: str,
    session_id: str,
    action: str,
    stage: str,
    owner: str = "和新红",
    platform: str = "job51",
    resume_handling: str = "",
    anomaly: bool = False,
    anomaly_reasons: list[str] | None = None,
) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "event": "contact_result",
        "owner": owner,
        "platform": platform,
        "classification": {
            "is_anomaly": anomaly,
            "reasons": anomaly_reasons or [],
        },
        "summary": {
            "processed": 1,
            "canonicalSessionId": session_id,
            "conversationId": f"conversation-{session_id}",
            "nextAction": action,
            "stage": stage,
            "resumeHandling": resume_handling,
        },
        "response": {
            "processed": 1,
            "canonicalSessionId": session_id,
            "conversationId": f"conversation-{session_id}",
            "nextAction": action,
            "stage": stage,
            "decision": {"action": action, "result": {}},
        },
    }
