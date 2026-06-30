"""Resume job-scope permission tests for Feishu members."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.auth.feishu_oauth import FeishuProfile
from app.control_plane.main import create_app
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.domain.resume.service import ResumeService
from app.domain.resume_review.repository import ResumeReviewRepository
from app.domain.resume_review.service import ResumeReviewService
from app.settings import load_settings
from fastapi.testclient import TestClient


@dataclass
class FakeFeishuOAuth:
    """Test double for Feishu OAuth user lookup."""

    profile: FeishuProfile

    def authorization_url(self, *, state: str) -> dict[str, str]:
        return {"url": f"https://feishu.example/oauth?state={state}", "state": state}

    async def exchange_code(self, code: str) -> FeishuProfile:
        assert code == "ok-code"
        return self.profile


def test_operation_member_only_reads_operation_ab_resumes(monkeypatch) -> None:
    """佘欣平 / 杨梅 only see operation A/B resumes."""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a")
    load_settings.cache_clear()
    app = _app_for_member("ou_she", "佘欣平")

    with TestClient(app) as client:
        _feishu_login(client)
        listed = client.get("/api/resumes")
        forbidden = client.get("/api/resumes/resume-finance")

    load_settings.cache_clear()
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == ["resume-operation"]
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "resume_forbidden"


def test_member_review_queue_filters_out_forbidden_resumes(monkeypatch, tmp_path: Path) -> None:
    """Review queue follows the same job-scope visibility as resume lists."""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a")
    load_settings.cache_clear()
    app = _app_for_member("ou_she", "佘欣平")
    service = _attach_review_service(app, tmp_path, assigned_to="feishu:ou_she")
    service.set_decision(
        resume_id="resume-operation",
        user_id="reviewer",
        decision="suitable",
        assign_to="feishu:ou_she",
    )
    service.set_decision(
        resume_id="resume-finance",
        user_id="reviewer",
        decision="suitable",
        assign_to="feishu:ou_she",
    )

    with TestClient(app) as client:
        _feishu_login(client)
        queue = client.get("/api/resume-review/queue")

    load_settings.cache_clear()
    assert queue.status_code == 200
    assert [item["resume"]["id"] for item in queue.json()["items"]] == ["resume-operation"]


def test_strategic_member_reads_ai_finance_and_investment(monkeypatch) -> None:
    """张怀滨 sees AI solution, finance, and investment-trading resumes."""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a")
    load_settings.cache_clear()
    app = _app_for_member("ou_zhang", "张怀滨")

    with TestClient(app) as client:
        _feishu_login(client)
        me = client.get("/api/auth/me")
        listed = client.get("/api/resumes")

    load_settings.cache_clear()
    assert me.status_code == 200
    assert set(me.json()["resumeScope"]["jobTypes"]) >= {
        "AI智能体解决方案负责人",
        "外部财务产品顾问",
        "投资交易策略研究员",
    }
    assert {item["id"] for item in listed.json()["items"]} == {
        "resume-ai",
        "resume-finance",
        "resume-investment",
    }


def _app_for_member(open_id: str, name: str):
    app = create_app()
    app.state.feishu_oauth_service = FakeFeishuOAuth(
        FeishuProfile(open_id=open_id, tenant_key="tenant-a", name=name),
    )
    repository = ResumeRepository.in_memory(
        [
            _record("resume-operation", "运营A"),
            _record("resume-ai", "AI智能体解决方案负责人"),
            _record("resume-finance", "外部财务产品顾问"),
            _record("resume-investment", "投资交易策略研究员（量化与市场情绪方向）"),
        ]
    )
    app.state.resume_repository = repository
    app.state.resume_service = ResumeService(repository)
    return app


def _attach_review_service(
    app,
    tmp_path: Path,
    *,
    assigned_to: str,
) -> ResumeReviewService:
    repository = ResumeReviewRepository(tmp_path / "review.sqlite")
    service = ResumeReviewService(
        repository,
        resume_repository=app.state.resume_repository,
        default_assignee=assigned_to,
    )
    app.state.resume_review_service = service
    return service


def _feishu_login(client: TestClient) -> None:
    start = client.get("/api/auth/feishu/start", follow_redirects=False)
    state = start.headers["location"].split("state=", 1)[1]
    response = client.get(
        f"/api/auth/feishu/callback?code=ok-code&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 307


def _record(resume_id: str, job_type: str):
    return Resume(
        id=resume_id,
        name=resume_id,
        phone="13800138000",
        job_type=job_type,
        payload={"rawText": f"{resume_id} {job_type}"},
    ).to_record()
