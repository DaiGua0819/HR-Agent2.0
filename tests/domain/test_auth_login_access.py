"""Login and UI access contract tests."""

from __future__ import annotations

from pathlib import Path

from app.control_plane.main import create_app
from fastapi.testclient import TestClient


def test_me_requires_login_session() -> None:
    """Anonymous users must see the login screen before app data."""

    with TestClient(create_app()) as client:
        response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "not_authenticated"


def test_admin_login_returns_full_ui_access() -> None:
    """Administrators land on the dashboard and can see every manager page."""

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert "hr_agent_session" in response.cookies
        assert payload["uiAccess"]["defaultView"] == "dashboard"
        assert set(payload["uiAccess"]["views"]) == {
            "dashboard",
            "resumes",
            "queue",
            "interviews",
            "automation",
            "rules",
        }
        assert "automation:run" in payload["permissions"]

        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["user"]["id"] == "local-admin"


def test_login_session_survives_control_plane_restart(tmp_path: Path) -> None:
    """A valid login cookie should survive a control-plane process restart."""

    session_store = tmp_path / "auth_sessions.sqlite"
    first_app = create_app()
    first_app.state.auth_session_store_path = session_store
    with TestClient(first_app) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )

    assert response.status_code == 200
    token = response.cookies.get("hr_agent_session")
    assert token

    restarted_app = create_app()
    restarted_app.state.auth_session_store_path = session_store
    with TestClient(restarted_app) as client:
        me = client.get("/api/auth/me", headers={"cookie": f"hr_agent_session={token}"})

    assert me.status_code == 200
    assert me.json()["user"]["id"] == "local-admin"


def test_logout_invalidates_persisted_login_session(tmp_path: Path) -> None:
    """Logout should remove the stored session so old cookies cannot be reused."""

    session_store = tmp_path / "auth_sessions.sqlite"
    app = create_app()
    app.state.auth_session_store_path = session_store
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        token = response.cookies.get("hr_agent_session")
        assert token
        logout = client.post(
            "/api/auth/logout",
            headers={"cookie": f"hr_agent_session={token}"},
        )

    assert logout.status_code == 200

    restarted_app = create_app()
    restarted_app.state.auth_session_store_path = session_store
    with TestClient(restarted_app) as client:
        me = client.get("/api/auth/me", headers={"cookie": f"hr_agent_session={token}"})

    assert me.status_code == 401
    assert me.json()["detail"] == "not_authenticated"


def test_expired_persisted_login_session_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Expired persisted sessions should behave the same as anonymous requests."""

    session_store = tmp_path / "auth_sessions.sqlite"
    times = iter([1000.0, 1002.0])
    monkeypatch.setattr("app.api.routes.auth._now", lambda: next(times))
    app = create_app()
    app.state.auth_session_store_path = session_store
    app.state.auth_session_ttl_seconds = 1
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin"},
        )
        token = response.cookies.get("hr_agent_session")
        assert token
        me = client.get("/api/auth/me", headers={"cookie": f"hr_agent_session={token}"})

    assert me.status_code == 401
    assert me.json()["detail"] == "not_authenticated"


def test_member_login_is_limited_to_resume_library() -> None:
    """Normal members only receive resume-library navigation and actions."""

    with TestClient(create_app()) as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "member", "password": "member"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["id"] == "local-member"
    assert payload["uiAccess"]["defaultView"] == "resumes"
    assert payload["uiAccess"]["views"] == ["resumes"]
    assert "automation:run" not in payload["permissions"]
    assert payload["resumeScope"]["includeUnlinked"] is False
    assert payload["resumeScope"]["jobTypes"] == []


def test_logout_clears_login_session() -> None:
    """Logout removes the session cookie and makes /me anonymous again."""

    with TestClient(create_app()) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        logout = client.post("/api/auth/logout")
        me = client.get("/api/auth/me")

    assert logout.status_code == 200
    assert me.status_code == 401


def test_local_dev_login_redirects_into_app() -> None:
    """Loopback browser testing can enter the authenticated app without Feishu OAuth."""

    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        response = client.get("/api/auth/dev-login?username=admin", follow_redirects=False)
        me = client.get("/api/auth/me")

    assert response.status_code == 307
    assert response.headers["location"] == "/index.html"
    assert "hr_agent_session" in response.cookies
    assert me.status_code == 200
    assert me.json()["user"]["id"] == "local-admin"


def test_local_dev_login_can_preview_zhang_huaibin_scope() -> None:
    """Loopback browser testing can preview Zhang Huaibin's member resume scope."""

    with TestClient(create_app(), base_url="http://127.0.0.1") as client:
        response = client.get(
            "/api/auth/dev-login?username=zhanghuaibin",
            follow_redirects=False,
        )
        me = client.get("/api/auth/me")

    assert response.status_code == 307
    assert response.headers["location"] == "/index.html"
    assert me.status_code == 200
    payload = me.json()
    assert payload["user"]["id"] == "local-zhanghuaibin"
    assert payload["uiAccess"]["views"] == ["resumes"]
    assert payload["resumeScope"]["jobTypes"] == [
        "AI智能体解决方案负责人",
        "外部财务产品顾问",
        "投资交易策略研究员（量化与市场情绪方向）",
        "AI产品经理",
    ]


def test_dev_login_rejects_non_loopback_hosts() -> None:
    """The development login shortcut must not be exposed on remote hostnames."""

    with TestClient(create_app(), base_url="http://example.com") as client:
        response = client.get("/api/auth/dev-login?username=admin", follow_redirects=False)

    assert response.status_code == 404


def test_frontend_has_feishu_only_login_screen_and_ui_access_hooks() -> None:
    """The static app starts at a Feishu-only production login screen."""

    root = Path(__file__).resolve().parents[2]
    html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    script = (
        (root / "frontend" / "app.js").read_text(encoding="utf-8")
        + (root / "frontend" / "auth.js").read_text(encoding="utf-8")
    )

    assert 'id="loginScreen"' in html
    assert 'id="feishuLoginBtn"' in html
    assert 'id="loginForm"' not in html
    assert "admin / member" not in html
    assert "uiAccess" in script
    assert "/api/auth/feishu/start" in script
    assert "setAllowedNavigation" in script
    assert "/api/auth/login" not in script


def test_feishu_login_button_uses_green_white_visual_treatment() -> None:
    """The Feishu login CTA should use the requested green-white button styling."""

    root = Path(__file__).resolve().parents[2]
    html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    styles = (root / "frontend" / "auth.css").read_text(encoding="utf-8")

    assert "/assets/auth.css?v=20260701-green-feishu-login" in html
    assert ".feishu-login {" in styles
    login_block = styles.split(".feishu-login {", 1)[1].split("}", 1)[0]

    assert "linear-gradient(135deg, #ffffff, #dcfce7 52%, #22c55e)" in login_block
    assert "color: #065f46" in login_block
    assert "rgba(22, 163, 74" in login_block


def test_login_screen_fits_codex_side_browser_viewport() -> None:
    """The Feishu login page should remain usable in the narrow Codex browser pane."""

    root = Path(__file__).resolve().parents[2]
    styles = (root / "frontend" / "auth.css").read_text(encoding="utf-8")

    assert "@media (max-width: 700px)" in styles
    side_browser_block = styles.split("@media (max-width: 700px)", 1)[1]
    login_block = side_browser_block.split(".login-screen {", 1)[1].split("}", 1)[0]
    visual_block = side_browser_block.split(".login-visual {", 1)[1].split("}", 1)[0]
    card_block = side_browser_block.split(".login-card {", 1)[1].split("}", 1)[0]

    assert "grid-template-columns: minmax(0, 1fr)" in login_block
    assert "height: 100dvh" in login_block
    assert "overflow-x: hidden" in login_block
    assert "overflow-y: auto" in login_block
    assert "min-height: 220px" in visual_block
    assert "padding: 20px" in card_block
