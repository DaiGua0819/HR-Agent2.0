from __future__ import annotations

from pathlib import Path

from app.features.interview_center.feishu.bitable import (
    find_existing_bitable_record,
    pick_existing_bitable_fields,
)
from app.features.interview_center.feishu.routes import resolve_bitable_target
from app.features.interview_center.store import SQLiteInterviewStore


def test_bitable_route_resolution_uses_old_default_tables() -> None:
    ai = resolve_bitable_target({"resume": {"jobType": "AI应用开发实习生"}})
    hr = resolve_bitable_target({"resume": {"position": "HRBP"}})
    ops_b = resolve_bitable_target({"session": {"title": "B端社交媒体运营负责人面试"}})

    assert ai.table_id == "tblJTlyRbGdsbJmM"
    assert ai.table_name == "AI实习生"
    assert ai.route_matched is True
    assert ai.route_keyword == "AI应用开发实习生"
    assert hr.table_id == "tblbADJqkdRhRlxv"
    assert hr.table_name == "HR"
    assert ops_b.table_id == "tblXyHjYr0Ba1rhe"
    assert ops_b.table_name == "运营B表"


def test_bitable_record_matching_prefers_phone_over_name() -> None:
    records = [
        {"record_id": "name-record", "fields": {"姓名": "Alice"}},
        {
            "record_id": "phone-record",
            "fields": {"候选人联系电话": [{"text": "13800138000"}], "姓名": "Carol"},
        },
    ]

    match = find_existing_bitable_record(
        records,
        {"name": "Alice", "phone": "138 0013 8000"},
    )

    assert match.record["record_id"] == "phone-record"
    assert match.reason == "phone_match"


def test_bitable_record_matching_uses_single_exact_name_match() -> None:
    records = [
        {"record_id": "other", "fields": {"姓名": "Bob"}},
        {"record_id": "alice", "fields": {"候选人姓名": "Alice"}},
    ]

    match = find_existing_bitable_record(records, {"name": "Alice"})

    assert match.record["record_id"] == "alice"
    assert match.reason == "name_match"


def test_bitable_record_matching_skips_ambiguous_names() -> None:
    records = [
        {"record_id": "alice-1", "fields": {"姓名": "Alice"}},
        {"record_id": "alice-2", "fields": {"候选人姓名": "Alice"}},
    ]

    match = find_existing_bitable_record(records, {"name": "Alice"})

    assert match.record is None
    assert match.reason == "ambiguous_name_match"
    assert match.count == 2


def test_pick_existing_bitable_fields_filters_to_field_map() -> None:
    fields = {
        "姓名": "Alice",
        "候选人联系电话": "13800138000",
        "职位": "",
        "未知字段": "drop",
        "空值": None,
    }
    field_map = {
        "byName": {
            "姓名": {"field_name": "姓名"},
            "候选人联系电话": {"field_name": "候选人联系电话"},
            "职位": {"field_name": "职位"},
        }
    }

    assert pick_existing_bitable_fields(fields, field_map) == {
        "姓名": "Alice",
        "候选人联系电话": "13800138000",
    }


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
