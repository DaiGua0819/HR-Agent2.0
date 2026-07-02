from __future__ import annotations

from pathlib import Path

from app.features.interview_center.store import SQLiteInterviewStore


def test_sqlite_store_upserts_calendar_event_by_feishu_event_id(tmp_path: Path) -> None:
    database = tmp_path / "interview.sqlite"
    store = SQLiteInterviewStore(database)

    first = store.upsert_from_calendar_event(
        {
            "feishuEventId": "event-1",
            "calendarId": "primary",
            "title": "Alice AI intern interview",
            "description": "first round",
            "startTime": 1_783_000_000,
            "endTime": 1_783_003_600,
            "isInterviewLike": True,
            "status": "synced",
        }
    )
    second = store.upsert_from_calendar_event(
        {
            "feishuEventId": "event-1",
            "calendarId": "primary",
            "title": "Alice AI intern interview updated",
            "description": "first round updated",
            "startTime": 1_783_000_100,
            "endTime": 1_783_003_700,
            "isInterviewLike": True,
            "status": "synced",
        }
    )

    assert second.id == first.id
    assert second.feishu_event_id == "event-1"
    assert second.calendar_id == "primary"
    assert second.start_time == 1_783_000_100
    assert second.end_time == 1_783_003_700
    assert second.payload["title"] == "Alice AI intern interview updated"
    assert len(store.list()) == 1


def test_sqlite_store_persists_feishu_oauth_token(tmp_path: Path) -> None:
    database = tmp_path / "interview.sqlite"
    store = SQLiteInterviewStore(database)

    store.save_token(
        {
            "accessToken": "user-access",
            "refreshToken": "refresh",
            "expiresAt": 1_783_100_000_000,
            "userInfo": {"open_id": "ou_1", "name": "HR"},
        }
    )

    restored = SQLiteInterviewStore(database).get_token()
    assert restored == {
        "accessToken": "user-access",
        "refreshToken": "refresh",
        "expiresAt": 1_783_100_000_000,
        "userInfo": {"open_id": "ou_1", "name": "HR"},
    }

    store.clear_token()
    assert SQLiteInterviewStore(database).get_token() is None


def test_sqlite_store_appends_and_lists_interview_logs(tmp_path: Path) -> None:
    database = tmp_path / "interview.sqlite"
    store = SQLiteInterviewStore(database)
    session = store.create(resume_id="resume-1", candidate_name="Alice", job_type="AI")

    store.append_log(session.id, "info", "calendar synced", {"total": 2})
    store.append_log(session.id, "warn", "bitable skipped", {"reason": "missing_config"})
    store.append_log("", "info", "global event", {})

    session_logs = store.list_logs(session.id, limit=10)
    assert [item["level"] for item in session_logs] == ["warn", "info"]
    assert session_logs[0]["message"] == "bitable skipped"
    assert session_logs[0]["payload"] == {"reason": "missing_config"}

    all_logs = store.list_logs("", limit=2)
    assert len(all_logs) == 2
    assert all_logs[0]["message"] == "global event"
