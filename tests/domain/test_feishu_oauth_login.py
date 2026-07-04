"""Feishu OAuth login contract tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from app.auth.feishu_oauth import FeishuProfile
from app.control_plane.main import create_app
from app.settings import load_settings
from fastapi.testclient import TestClient


@dataclass
class FakeFeishuOAuth:
    """Test double for Feishu OAuth network calls."""

    profile: FeishuProfile

    def authorization_url(self, *, state: str) -> dict[str, str]:
        return {"url": f"https://feishu.example/oauth?state={state}", "state": state}

    async def exchange_code(self, code: str) -> FeishuProfile:
        assert code == "ok-code"
        return self.profile


def _app_with_feishu(profile: FeishuProfile):
    app = create_app()
    app.state.feishu_oauth_service = FakeFeishuOAuth(profile)
    return app


def test_feishu_start_redirects_to_authorization_url() -> None:
    """The login button can start a Feishu OAuth authorization flow."""

    app = _app_with_feishu(
        FeishuProfile(open_id="ou_admin", tenant_key="tenant-a", name="王鑫力"),
    )

    with TestClient(app) as client:
        response = client.get("/api/auth/feishu/start", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://feishu.example/oauth?state=")


def test_feishu_start_uses_login_redirect_uri_when_interview_redirect_is_configured(
    monkeypatch,
) -> None:
    """The first login authorization should return to the admin console callback."""

    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret_test")
    monkeypatch.setenv(
        "FEISHU_REDIRECT_URI",
        "http://127.0.0.1:18080/api/interview-center/feishu/oauth/callback",
    )
    monkeypatch.setenv(
        "FEISHU_LOGIN_REDIRECT_URI",
        "http://127.0.0.1:18080/api/auth/feishu/callback",
    )
    load_settings.cache_clear()
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/auth/feishu/start", follow_redirects=False)

    load_settings.cache_clear()
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["redirect_uri"] == ["http://127.0.0.1:18080/api/auth/feishu/callback"]


def test_feishu_callback_rejects_invalid_state() -> None:
    """Callbacks without a state issued by this server are rejected."""

    app = _app_with_feishu(
        FeishuProfile(open_id="ou_admin", tenant_key="tenant-a", name="王鑫力"),
    )

    with TestClient(app) as client:
        response = client.get("/api/auth/feishu/callback?code=ok-code&state=bad")

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_oauth_state"


def test_feishu_callback_rejects_unallowed_company(monkeypatch) -> None:
    """Only the configured company tenant can create a session."""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a")
    load_settings.cache_clear()
    app = _app_with_feishu(
        FeishuProfile(open_id="ou_user", tenant_key="tenant-b", name="候选成员"),
    )

    with TestClient(app) as client:
        start = client.get("/api/auth/feishu/start", follow_redirects=False)
        state = start.headers["location"].split("state=", 1)[1]
        response = client.get(f"/api/auth/feishu/callback?code=ok-code&state={state}")

    load_settings.cache_clear()
    assert response.status_code == 403
    assert response.json()["detail"] == "company_not_allowed"


def test_feishu_callback_maps_bootstrap_admin_by_name(monkeypatch) -> None:
    """Before open_id is known, configured bootstrap admin names can enter as admin."""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a")
    monkeypatch.delenv("FEISHU_ADMIN_OPEN_IDS", raising=False)
    load_settings.cache_clear()
    app = _app_with_feishu(
        FeishuProfile(open_id="ou_wang", tenant_key="tenant-a", name="王鑫力"),
    )

    with TestClient(app) as client:
        start = client.get("/api/auth/feishu/start", follow_redirects=False)
        state = start.headers["location"].split("state=", 1)[1]
        response = client.get(
            f"/api/auth/feishu/callback?code=ok-code&state={state}",
            follow_redirects=False,
        )
        me = client.get("/api/auth/me")

    load_settings.cache_clear()
    assert response.status_code == 307
    assert me.status_code == 200
    payload = me.json()
    assert payload["roles"] == ["super_admin"]
    assert payload["authProvider"] == "feishu"
    assert payload["feishu"]["openId"] == "ou_wang"
    assert payload["feishu"]["adminMatchedBy"] == "bootstrap_name"


def test_feishu_callback_maps_hexinhong_as_bootstrap_admin(monkeypatch) -> None:
    """和新红 is a configured bootstrap admin and should enter as super admin."""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a")
    monkeypatch.delenv("FEISHU_ADMIN_OPEN_IDS", raising=False)
    load_settings.cache_clear()
    app = _app_with_feishu(
        FeishuProfile(open_id="ou_hexinhong", tenant_key="tenant-a", name="和新红"),
    )

    with TestClient(app) as client:
        start = client.get("/api/auth/feishu/start", follow_redirects=False)
        state = start.headers["location"].split("state=", 1)[1]
        response = client.get(
            f"/api/auth/feishu/callback?code=ok-code&state={state}",
            follow_redirects=False,
        )
        me = client.get("/api/auth/me")

    load_settings.cache_clear()
    assert response.status_code == 307
    assert me.status_code == 200
    payload = me.json()
    assert payload["roles"] == ["super_admin"]
    assert payload["uiAccess"]["defaultView"] == "dashboard"
    assert payload["feishu"]["adminMatchedBy"] == "bootstrap_name"


def test_feishu_callback_keeps_bootstrap_admin_names_after_open_id_is_set(
    monkeypatch,
) -> None:
    """Known admin names stay admin until every admin open_id has been collected."""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a")
    monkeypatch.setenv("FEISHU_ADMIN_OPEN_IDS", "ou_wang")
    monkeypatch.setenv("FEISHU_BOOTSTRAP_ADMIN_NAMES", "He Admin")
    load_settings.cache_clear()
    app = _app_with_feishu(
        FeishuProfile(open_id="ou_he", tenant_key="tenant-a", name="He Admin"),
    )

    with TestClient(app) as client:
        start = client.get("/api/auth/feishu/start", follow_redirects=False)
        state = start.headers["location"].split("state=", 1)[1]
        client.get(
            f"/api/auth/feishu/callback?code=ok-code&state={state}",
            follow_redirects=False,
        )
        me = client.get("/api/auth/me")

    load_settings.cache_clear()
    assert me.status_code == 200
    payload = me.json()
    assert payload["roles"] == ["super_admin"]
    assert payload["feishu"]["adminMatchedBy"] == "bootstrap_name"


def test_feishu_callback_maps_member_to_resume_library(monkeypatch) -> None:
    """Company users who are not admins become resume-library-only members."""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "tenant-a")
    monkeypatch.setenv("FEISHU_ADMIN_OPEN_IDS", "ou_admin")
    load_settings.cache_clear()
    app = _app_with_feishu(
        FeishuProfile(open_id="ou_member", tenant_key="tenant-a", name="普通同事"),
    )

    with TestClient(app) as client:
        start = client.get("/api/auth/feishu/start", follow_redirects=False)
        state = start.headers["location"].split("state=", 1)[1]
        client.get(
            f"/api/auth/feishu/callback?code=ok-code&state={state}",
            follow_redirects=False,
        )
        me = client.get("/api/auth/me")

    load_settings.cache_clear()
    assert me.status_code == 200
    payload = me.json()
    assert payload["roles"] == ["member"]
    assert payload["uiAccess"]["views"] == ["resumes"]
    assert payload["resumeScope"]["owners"] == ["普通同事"]
    assert payload["resumeScope"]["jobTypes"] == []


def test_feishu_callback_writes_login_diagnostics(tmp_path, monkeypatch) -> None:
    """A successful Feishu login leaves a safe identity snapshot for bootstrap setup."""

    monkeypatch.setenv("FEISHU_ALLOWED_TENANT_KEYS", "")
    load_settings.cache_clear()
    app = _app_with_feishu(
        FeishuProfile(open_id="ou_first", tenant_key="tenant-first", name="Admin One"),
    )
    diagnostics_path = tmp_path / "last_feishu_login.json"
    app.state.feishu_login_diagnostics_path = diagnostics_path

    with TestClient(app) as client:
        start = client.get("/api/auth/feishu/start", follow_redirects=False)
        state = start.headers["location"].split("state=", 1)[1]
        response = client.get(
            f"/api/auth/feishu/callback?code=ok-code&state={state}",
            follow_redirects=False,
        )

    load_settings.cache_clear()
    assert response.status_code == 307
    payload = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    assert payload["feishu"]["openId"] == "ou_first"
    assert payload["feishu"]["tenantKey"] == "tenant-first"
    assert "accessToken" not in json.dumps(payload)
