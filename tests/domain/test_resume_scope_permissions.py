"""Resume job-scope permission tests for Feishu members."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from app.auth.feishu_oauth import FeishuProfile
from app.control_plane.main import create_app
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.domain.resume.service import ResumeService
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
    assert listed.json()["jobFacets"][0]["jobType"] == "运营A"
    assert listed.json()["items"][0]["displayJobType"] == "运营A"


def test_operation_member_alias_xinping_gets_same_scope(monkeypatch) -> None:
    """佘新平 is treated as the same operation-scope member alias."""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a")
    load_settings.cache_clear()
    app = _app_for_member("ou_she_alias", "佘新平")

    with TestClient(app) as client:
        _feishu_login(client)
        me = client.get("/api/auth/me")
        listed = client.get("/api/resumes")

    load_settings.cache_clear()
    assert me.status_code == 200
    assert me.json()["resumeScope"]["jobTypes"] == ["运营A", "运营B"]
    assert [item["id"] for item in listed.json()["items"]] == ["resume-operation"]


def test_unconfigured_member_cannot_read_seed_resumes(monkeypatch) -> None:
    """Unconfigured members default to no job scope instead of seeing all seed resumes."""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a")
    load_settings.cache_clear()
    app = _app_for_member("ou_unknown", "未配置同事")

    with TestClient(app) as client:
        _feishu_login(client)
        listed = client.get("/api/resumes")

    load_settings.cache_clear()
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    assert listed.json()["total"] == 0


def test_member_cannot_read_shared_admin_queue(monkeypatch, tmp_path: Path) -> None:
    """Members cannot enumerate the shared administrator review inbox."""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a")
    load_settings.cache_clear()
    app = _app_for_member("ou_she", "佘欣平")

    with TestClient(app) as client:
        _feishu_login(client)
        queue = client.get("/api/resume-review/queue")

    load_settings.cache_clear()
    assert queue.status_code == 403
    assert queue.json()["detail"] == "admin_queue_forbidden"


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
    assert me.json()["resumeScope"]["jobTypes"] == [
        "AI智能体解决方案负责人",
        "外部财务产品顾问",
        "投资交易策略研究员（量化与市场情绪方向）",
        "AI产品经理",
    ]
    assert {item["id"] for item in listed.json()["items"]} == {
        "resume-ai",
        "resume-finance",
        "resume-investment",
        "resume-investment-short",
        "resume-ai-product-manager",
    }
    assert [
        item
        for item in listed.json()["jobFacets"]
        if item["jobType"] == "投资交易策略研究员（量化与市场情绪方向）"
    ] == [{"jobType": "投资交易策略研究员（量化与市场情绪方向）", "count": 2}]


def test_ai_intern_member_only_reads_ai_intern_resumes(monkeypatch) -> None:
    """马弘毅登录后只看到 AI 实习生岗位简历。"""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a")
    load_settings.cache_clear()
    app = _app_for_member("ou_ma", "马弘毅")

    with TestClient(app) as client:
        _feishu_login(client)
        me = client.get("/api/auth/me")
        listed = client.get("/api/resumes")
        forbidden = client.get("/api/resumes/resume-operation")

    load_settings.cache_clear()
    assert me.status_code == 200
    assert me.json()["resumeScope"]["jobTypes"] == ["AI应用开发实习生"]
    assert [item["id"] for item in listed.json()["items"]] == ["resume-ai-intern"]
    assert listed.json()["jobFacets"] == [{"jobType": "AI应用开发实习生", "count": 1}]
    assert forbidden.status_code == 403


def test_caihua_member_only_reads_ai_product_manager_resumes(monkeypatch) -> None:
    """Caihua can only read AI product manager resumes."""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a")
    load_settings.cache_clear()
    app = _app_for_member("ou_caihua", "菜花")

    with TestClient(app) as client:
        _feishu_login(client)
        me = client.get("/api/auth/me")
        listed = client.get("/api/resumes")
        forbidden_operation = client.get("/api/resumes/resume-operation")
        forbidden_finance = client.get("/api/resumes/resume-finance")

    load_settings.cache_clear()
    assert me.status_code == 200
    assert me.json()["resumeScope"]["jobTypes"] == ["AI产品经理"]
    assert [item["id"] for item in listed.json()["items"]] == ["resume-ai-product-manager"]
    assert listed.json()["jobFacets"] == [{"jobType": "AI产品经理", "count": 1}]
    assert forbidden_operation.status_code == 403
    assert forbidden_finance.status_code == 403


def test_resume_download_uses_candidate_and_job_filename(monkeypatch, tmp_path: Path) -> None:
    """点击简历预览下载时使用 姓名_岗位.pdf 文件名，不额外限制岗位范围。"""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a")
    load_settings.cache_clear()
    pdf_path = tmp_path / "source.pdf"
    content = b"%PDF-1.4\nfake resume\n%%EOF"
    pdf_path.write_bytes(content)
    operation_pdf_path = tmp_path / "operation.pdf"
    operation_content = b"%PDF-1.4\noperation resume\n%%EOF"
    operation_pdf_path.write_bytes(operation_content)
    app = create_app()
    app.state.feishu_oauth_service = FakeFeishuOAuth(
        FeishuProfile(open_id="ou_ma", tenant_key="tenant-a", name="马弘毅"),
    )
    repository = ResumeRepository.in_memory(
        [
            Resume(
                id="resume-ai-intern-file",
                name="候选人甲",
                phone="13800138000",
                job_type="AI应用开发实习生",
                payload={"downloadPath": str(pdf_path)},
            ).to_record(),
            Resume(
                id="resume-operation",
                name="运营候选人",
                phone="13800138001",
                job_type="企业内容运营负责人（B2B/短视频方向）",
                payload={"downloadPath": str(operation_pdf_path)},
            ).to_record(),
        ]
    )
    app.state.resume_repository = repository
    app.state.resume_service = ResumeService(repository)

    with TestClient(app) as client:
        _feishu_login(client)
        downloaded = client.get("/api/resumes/resume-ai-intern-file/download")
        out_of_scope_downloaded = client.get("/api/resumes/resume-operation/download")

    load_settings.cache_clear()
    assert downloaded.status_code == 200
    assert downloaded.content == content
    disposition = downloaded.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert quote("候选人甲_AI应用开发实习生.pdf") in disposition
    assert out_of_scope_downloaded.status_code == 200
    assert out_of_scope_downloaded.content == operation_content


def _app_for_member(open_id: str, name: str):
    app = create_app()
    app.state.feishu_oauth_service = FakeFeishuOAuth(
        FeishuProfile(open_id=open_id, tenant_key="tenant-a", name=name),
    )
    repository = ResumeRepository.in_memory(
        [
            _record("resume-operation", "企业内容运营负责人（B2B/短视频方向）"),
            _record("resume-ai", "AI智能体解决方案负责人"),
            _record("resume-finance", "外部财务产品顾问"),
            _record("resume-investment", "投资交易策略研究员（量化与市场情绪方向）"),
            _record("resume-investment-short", "投资交易策略研究员"),
            _record("resume-ai-product-manager", "AI Product Manager"),
            _record("resume-ai-intern", "AI应用开发实习生"),
        ]
    )
    app.state.resume_repository = repository
    app.state.resume_service = ResumeService(repository)
    return app


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
