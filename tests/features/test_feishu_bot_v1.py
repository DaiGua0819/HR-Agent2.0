from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from app.features.feishu_bot.access import FeishuBotAccessPolicy
from app.features.feishu_bot.models import BotEvent
from app.features.feishu_bot.repository import (
    FeishuBotRepository,
    redact_sensitive_text,
)


def _event(
    *,
    event_id: str = "event-1",
    message_id: str = "om-message-1",
    sender_id: str = "ou-member",
) -> BotEvent:
    return BotEvent(
        event_id=event_id,
        message_id=message_id,
        sender_open_id=sender_id,
        chat_id="oc-chat-1",
        chat_type="p2p",
        message_type="text",
        content="今天处理了多少人",
        create_time="1784160000000",
    )


def test_event_repository_claims_event_and_message_only_once(tmp_path: Path) -> None:
    repository = FeishuBotRepository(tmp_path / "bot.sqlite")

    assert repository.claim_event(_event()) is True
    assert repository.claim_event(_event()) is False
    assert repository.claim_event(_event(event_id="event-2")) is False
    assert repository.claim_event(_event(message_id="om-message-2")) is False

    with sqlite3.connect(tmp_path / "bot.sqlite") as connection:
        assert connection.execute("SELECT COUNT(*) FROM feishu_bot_events").fetchone()[0] == 1


def test_event_repository_reclaims_stale_processing_event(tmp_path: Path) -> None:
    database = tmp_path / "bot.sqlite"
    repository = FeishuBotRepository(database)
    event = _event()
    assert repository.claim_event(event) is True
    repository.mark_processing(event.event_id)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE feishu_bot_events SET started_at = ? WHERE event_id = ?",
            ("2000-01-01T00:00:00+00:00", event.event_id),
        )
        connection.commit()

    assert repository.claim_event(event) is True
    assert repository.claim_event(event) is False


def test_event_repository_tracks_lifecycle_and_redacts_turn_text(tmp_path: Path) -> None:
    repository = FeishuBotRepository(tmp_path / "bot.sqlite")
    event = _event()
    assert repository.claim_event(event) is True

    repository.mark_processing(event.event_id)
    repository.append_turn(
        event_id=event.event_id,
        chat_id=event.chat_id,
        sender_open_id=event.sender_open_id,
        actor_name="测试成员",
        intent="resume_counts",
        question=(
            "查 13800138000 和 test@example.com，"
            "access_token=secret-value " + "问" * 1200
        ),
        response="共有 3 份简历 " + "答" * 5000,
    )
    repository.mark_completed(event.event_id, response_message_id="om-reply-1")

    stored = repository.get_event(event.event_id)
    assert stored is not None
    assert stored["status"] == "completed"
    assert stored["response_message_id"] == "om-reply-1"
    turns = repository.recent_turns(event.chat_id, event.sender_open_id, limit=5)
    assert len(turns) == 1
    assert "13800138000" not in turns[0]["question"]
    assert "test@example.com" not in turns[0]["question"]
    assert "secret-value" not in turns[0]["question"]
    assert "[手机号]" in turns[0]["question"]
    assert "[邮箱]" in turns[0]["question"]
    assert "[敏感凭据]" in turns[0]["question"]
    assert len(turns[0]["question"]) <= 1000
    assert len(turns[0]["response"]) <= 4000


@pytest.mark.parametrize(
    ("value", "secrets"),
    [
        ("Authorization: Bearer super-secret-token", ("super-secret-token",)),
        (
            "Cookie: session=abc123; refresh=def456",
            ("abc123", "def456"),
        ),
        (
            "Authorization: AWS4-HMAC-SHA256 Credential=aws-key, Signature=aws-signature",
            ("aws-key", "aws-signature"),
        ),
        ('{"app_secret":"json-secret"}', ("json-secret",)),
        ('{"access_token":"json-token"}', ("json-token",)),
    ],
)
def test_redact_sensitive_text_covers_header_and_json_credential_shapes(
    value: str,
    secrets: tuple[str, ...],
) -> None:
    redacted = redact_sensitive_text(value)

    assert "[敏感凭据]" in redacted
    for secret in secrets:
        assert secret not in redacted


@pytest.mark.parametrize(
    "value",
    ["+86 138-0013-8000", "138 0013 8000"],
)
def test_redact_sensitive_text_covers_formatted_phone_numbers(value: str) -> None:
    redacted = redact_sensitive_text(f"联系电话：{value}")

    assert value not in redacted
    assert "[手机号]" in redacted


def test_bot_event_parses_lark_cli_payload() -> None:
    event = BotEvent.from_payload(
        {
            "event_id": "event-1",
            "message_id": "om-message-1",
            "sender_id": "ou-member",
            "chat_id": "oc-chat-1",
            "chat_type": "p2p",
            "message_type": "text",
            "content": "昨天呢？",
            "create_time": "1784160000000",
        }
    )

    assert event.sender_open_id == "ou-member"
    assert event.content == "昨天呢？"


def test_access_policy_requires_exact_open_id_and_never_matches_name(tmp_path: Path) -> None:
    config = tmp_path / "access.yaml"
    config.write_text(
        """
users:
  - openId: ou-member
    displayName: 菜花
    role: member
    jobTypes:
      - AI Product Manager
    reviewUserId: feishu:ou-existing-review-id
  - openId: ou-admin
    displayName: 王鑫力
    role: admin
    runtimeControl: true
    jobTypes:
      - '*'
""".strip(),
        encoding="utf-8",
    )

    policy = FeishuBotAccessPolicy(config)
    member = policy.resolve("ou-member")
    admin = policy.resolve("ou-admin")

    assert member is not None
    assert member.display_name == "菜花"
    assert member.role == "member"
    assert member.job_types == ("AI产品经理",)
    assert member.review_user_id == "feishu:ou-existing-review-id"
    assert member.can("query:resumes") is True
    assert member.can("query:workers") is False
    assert admin is not None
    assert admin.job_types == ("*",)
    assert admin.can("query:workers") is True
    assert admin.can("control:runtime") is True
    assert policy.resolve("菜花") is None
    assert policy.resolve("ou-unknown") is None


def test_admin_runtime_control_is_denied_unless_explicitly_enabled(tmp_path: Path) -> None:
    config = tmp_path / "access.yaml"
    config.write_text(
        """
users:
  - openId: ou-admin
    displayName: 只读管理员
    role: admin
    jobTypes:
      - '*'
""".strip(),
        encoding="utf-8",
    )

    actor = FeishuBotAccessPolicy(config).resolve("ou-admin")

    assert actor is not None
    assert actor.can("query:workers") is True
    assert actor.can("control:runtime") is False


def test_access_policy_rejects_duplicate_open_ids(tmp_path: Path) -> None:
    config = tmp_path / "access.yaml"
    config.write_text(
        """
users:
  - openId: ou-duplicate
    displayName: 成员甲
    role: member
    jobTypes: [运营A]
  - openId: ou-duplicate
    displayName: 成员乙
    role: member
    jobTypes: [运营B]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate_feishu_bot_open_id"):
        FeishuBotAccessPolicy(config)


def test_production_access_policy_uses_only_dedicated_app_open_ids() -> None:
    config = Path(__file__).resolve().parents[2] / "config" / "feishu_bot_access.yaml"

    policy = FeishuBotAccessPolicy(config)
    actors = {actor.display_name: actor for actor in policy.actors()}

    assert set(actors) == {"王鑫力"}
    assert actors["王鑫力"].open_id == "ou_0ae40de4ac0e63d584c9644e84b62d26"
    assert actors["王鑫力"].role == "admin"
    assert actors["王鑫力"].job_types == ("*",)
    assert actors["王鑫力"].review_user_id == (
        "feishu:ou_5707b9cf314d1aeb8dee5f1115dc1120"
    )
    assert policy.resolve("ou_5707b9cf314d1aeb8dee5f1115dc1120") is None
    assert policy.resolve("ou_acadfb85356a318fb1fc168be8fbfb75") is None
