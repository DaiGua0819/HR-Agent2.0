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


def test_logout_clears_login_session() -> None:
    """Logout removes the session cookie and makes /me anonymous again."""

    with TestClient(create_app()) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        logout = client.post("/api/auth/logout")
        me = client.get("/api/auth/me")

    assert logout.status_code == 200
    assert me.status_code == 401


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
