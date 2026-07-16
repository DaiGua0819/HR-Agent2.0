"""Phase 5：批量、邮箱、规则建议和控制面 API 测试。"""

from __future__ import annotations

import asyncio

from app.control_plane.main import create_app
from app.domain.batch.service import BatchService, parse_resume_text
from app.domain.email_import.imap_client import EmailAttachment, EmailMessage
from app.domain.email_import.service import EmailImportService
from app.domain.scoring.engine import POSITION_SCORING_VERSION
from app.domain.scoring.suggestions import GLOBAL_RULE_SUGGESTIONS
from fastapi.testclient import TestClient


def test_batch_parse_extracts_expected_resume_fields() -> None:
    """批量解析能从文本中提取姓名、手机号、学历和岗位。"""

    payload = parse_resume_text("张三\n电话 13800138000\n本科 电气工程师 PLC 项目")
    assert payload["name"] == "张三"
    assert payload["phone"] == "13800138000"
    assert payload["education"] == "本科"
    assert payload["applied_position"] == "电气工程师"

    service = BatchService()
    job = service.create_job(
        "auto",
        [{"fileName": "张三简历.txt", "content": "张三\n13800138000 本科 电气工程师"}],
    )
    assert job.status == "done"
    assert job.items[0].status == "done"


def test_email_import_uses_mockable_imap_client() -> None:
    """邮箱导入使用 mock 客户端，不依赖真实 IMAP。"""

    service = EmailImportService(
        client=FakeImapClient(
            [
                EmailMessage(
                    subject="李四简历",
                    sender="hr@example.com",
                    attachments=[
                        EmailAttachment(
                            file_name="李四.txt",
                            content="李四\n13900139000 本科 销售管培生".encode(),
                        )
                    ],
                )
            ]
        )
    )
    result = asyncio.run(service.import_resumes())
    assert result["imported"] == 1
    assert result["items"][0]["source"] == "email"
    assert result["items"][0]["phone"] == "13900139000"


def test_rule_suggestions_and_control_plane_routes_are_wired() -> None:
    """规则建议写内存桩，控制面挂载 Phase 5 API。"""

    GLOBAL_RULE_SUGGESTIONS.clear()
    with TestClient(create_app()) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        rules = client.get("/api/scoring/rules", params={"job_type": "电气工程师"})
        assert rules.status_code == 200
        assert rules.json()["version"] == POSITION_SCORING_VERSION

        suggestion = client.post(
            "/api/scoring/feedback",
            json={"resume_id": "resume-1", "feedback": "PLC 权重应更高"},
        )
        assert suggestion.status_code == 200
        suggestion_id = suggestion.json()["id"]
        accepted = client.post(f"/api/scoring/suggestions/{suggestion_id}/accept")
        assert accepted.json()["status"] == "accepted"

        resumes = client.get("/api/resumes")
        assert resumes.status_code == 200
        assert "items" in resumes.json()

        batch = client.post(
            "/api/batch/jobs",
            json={
                "parse_mode": "auto",
                "files": [{"fileName": "王五.txt", "content": "王五\n13800138000 本科 HRBP"}],
            },
        )
        assert batch.status_code == 200
        assert batch.json()["status"] == "done"

        email_status = client.get("/api/email/resumes/auto-status")
        assert email_status.json() == {"enabled": False}

        monitoring = client.get("/api/monitoring/overview")
        assert monitoring.status_code == 200
        assert monitoring.json()["status"] == "ok"


class FakeImapClient:
    """测试用 IMAP 客户端。"""

    def __init__(self, messages: list[EmailMessage]) -> None:
        self.messages = messages

    async def fetch_resume_messages(self) -> list[EmailMessage]:
        return self.messages
