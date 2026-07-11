"""简历审阅工作台领域测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.api.routes.auth import AuthSessionStore
from app.auth.access import user_payload
from app.control_plane.main import create_app
from app.db.engine import connect, run_migrations
from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.domain.resume.service import ResumeService
from app.domain.resume_review.models import LocalUser
from app.domain.resume_review.repository import ResumeReviewRepository
from app.domain.resume_review.service import ResumeReviewService
from fastapi.testclient import TestClient

SHARED_ADMIN_INBOX = "shared-admin-inbox"


def test_review_migration_creates_tables(tmp_path: Path) -> None:
    """迁移会幂等创建审阅状态和分配队列表。"""

    database = tmp_path / "review.sqlite"
    run_migrations(database)
    run_migrations(database)

    with connect(database) as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert {
        "resume_review_states",
        "resume_review_events",
        "resume_assignments",
        "resume_saved_views",
    } <= tables


def test_opening_resume_marks_current_user_viewed(tmp_path: Path) -> None:
    """打开工作台上下文会把当前用户标记为已看。"""

    resume_repo, service = _service(tmp_path)
    resume = _save_resume(resume_repo)

    context = service.context_for_resume(resume=resume, user_id="viewer-1")

    assert context["reviewState"]["readStatus"] == "viewed"
    assert service.state_for_resume("resume-1", "viewer-1").read_status == "viewed"


def test_suitable_decision_waits_for_explicit_admin_push(tmp_path: Path) -> None:
    """点合适只写成员判断，显式推送后才进入管理员待处理队列。"""

    resume_repo, service = _service(tmp_path)
    _save_resume(resume_repo)

    result = service.set_decision(
        resume_id="resume-1",
        user_id="viewer-1",
        decision="suitable",
        reason_tags=["岗位匹配"],
        note="建议复核",
    )

    assert result["state"]["decision"] == "suitable"
    assert result["state"]["assignedTo"] == ""
    assert result["assignment"] is None
    assert service.shared_admin_queue() == []

    pushed = service.push_to_admin(resume_id="resume-1", user_id="viewer-1")
    duplicate = service.push_to_admin(resume_id="resume-1", user_id="viewer-1")
    queue = service.shared_admin_queue()

    assert pushed["assignment"]["assignedToUserId"] == SHARED_ADMIN_INBOX
    assert duplicate["assignment"]["id"] == pushed["assignment"]["id"]
    assert len(queue) == 1
    assert queue[0]["resume"]["id"] == "resume-1"
    assert service.state_for_resume("resume-1", "viewer-1").assigned_to == SHARED_ADMIN_INBOX


def test_push_to_admin_rejects_non_suitable_decision(tmp_path: Path) -> None:
    """只有成员已标记合适的简历才能推送给管理员。"""

    resume_repo, service = _service(tmp_path)
    _save_resume(resume_repo)
    service.set_decision(
        resume_id="resume-1",
        user_id="viewer-1",
        decision="unsuitable",
        reason_tags=["经验不符"],
    )

    with pytest.raises(ValueError, match="resume_not_suitable_for_push"):
        service.push_to_admin(resume_id="resume-1", user_id="viewer-1")

    assert service.shared_admin_queue() == []


def test_unsuitable_decision_does_not_create_assignment(tmp_path: Path) -> None:
    """点不合适只写状态，不进入待处理队列。"""

    resume_repo, service = _service(tmp_path)
    _save_resume(resume_repo)

    result = service.set_decision(
        resume_id="resume-1",
        user_id="viewer-1",
        decision="unsuitable",
        reason_tags=["经验不符"],
        note="暂不匹配",
    )

    assert result["state"]["decision"] == "unsuitable"
    assert result["assignment"] is None
    assert service.shared_admin_queue() == []


def test_member_push_route_creates_admin_queue_after_suitable_decision(
    tmp_path: Path,
) -> None:
    """成员先点合适，再调用推送接口，管理员待处理才出现任务。"""

    app, service = _app_with_review_service(tmp_path)

    with TestClient(app) as client:
        client.post(
            "/api/auth/login",
            json={"username": "zhanghuaibin", "password": "zhanghuaibin"},
        )
        decision = client.post(
            "/api/resumes/resume-1/review-decision",
            json={"decision": "suitable", "reasonTags": ["岗位匹配"]},
        )
        pushed = client.post("/api/resumes/resume-1/push-to-admin")

    assert decision.status_code == 200
    assert decision.json()["assignment"] is None
    assert pushed.status_code == 200
    assert pushed.json()["assignment"]["assignedToUserId"] == SHARED_ADMIN_INBOX
    queue = service.shared_admin_queue()
    assert len(queue) == 1
    assert queue[0]["assignment"]["fromUserId"] == "local-zhanghuaibin"


def test_shared_admin_queue_is_completed_once_by_any_admin(tmp_path: Path) -> None:
    """All admins share one pending task, and one decision completes it for everyone."""

    resume_repo, service = _service(tmp_path)
    _save_resume(resume_repo)
    service.set_decision(
        resume_id="resume-1",
        user_id="feishu:member-a",
        user_name="成员甲",
        decision="suitable",
    )
    service.push_to_admin(
        resume_id="resume-1",
        user_id="feishu:member-a",
        user_name="成员甲",
    )

    first_admin_queue = service.shared_admin_queue()
    second_admin_queue = service.shared_admin_queue()
    completed = service.set_decision(
        resume_id="resume-1",
        user_id="feishu:admin-a",
        user_name="管理员甲",
        decision="needs_more_info",
        is_admin=True,
    )

    assert len(first_admin_queue) == len(second_admin_queue) == 1
    assert first_admin_queue[0]["assignment"]["assignedToUserId"] == SHARED_ADMIN_INBOX
    assert completed["completedAssignment"]["status"] == "completed"
    assert completed["completedAssignment"]["completedByUserId"] == "feishu:admin-a"
    assert completed["completedAssignment"]["completedByUserName"] == "管理员甲"
    assert service.shared_admin_queue() == []

    duplicate_completion = service.set_decision(
        resume_id="resume-1",
        user_id="feishu:admin-b",
        user_name="管理员乙",
        decision="suitable",
        is_admin=True,
    )
    assert duplicate_completion["completedAssignment"] is None


def test_reviewer_decisions_include_persisted_names_and_historical_fallback(tmp_path: Path) -> None:
    """Decision lists expose reviewer names without guessing historical identities."""

    resume_repo, service = _service(tmp_path)
    _save_resume(resume_repo)
    service.set_decision(
        resume_id="resume-1",
        user_id="feishu:member-a",
        user_name="成员甲",
        decision="suitable",
    )
    service.set_decision(
        resume_id="resume-1",
        user_id="legacy-user-1234",
        decision="unsuitable",
    )

    decisions = service.reviewer_decisions_for_resumes(["resume-1"])["resume-1"]
    by_user_id = {item["userId"]: item for item in decisions}

    assert by_user_id["feishu:member-a"]["userName"] == "成员甲"
    assert by_user_id["legacy-user-1234"]["userName"] == "历史账号（1234）"


def test_member_cannot_read_shared_admin_queue(tmp_path: Path) -> None:
    """Members can submit decisions but cannot enumerate the shared admin inbox."""

    app, _ = _app_with_review_service(tmp_path)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "member", "password": "member"})
        response = client.get("/api/resume-review/queue")

    assert response.status_code == 403
    assert response.json()["detail"] == "admin_queue_forbidden"


def test_two_feishu_admin_sessions_read_the_same_shared_pending_task(tmp_path: Path) -> None:
    """Shared tasks are keyed by the inbox, not an individual Feishu administrator ID."""

    app, service = _app_with_review_service(tmp_path)
    service.set_decision(resume_id="resume-1", user_id="member-1", decision="suitable")
    service.push_to_admin(resume_id="resume-1", user_id="member-1")
    session_store = AuthSessionStore(app.state.auth_session_store_path)
    for token, user_id, name in [
        ("admin-a-token", "feishu:admin-a", "管理员甲"),
        ("admin-b-token", "feishu:admin-b", "管理员乙"),
    ]:
        session_store.set(
            token,
            user_payload(
                LocalUser(
                    id=user_id,
                    name=name,
                    roles=["admin"],
                    permissions=["resumes:read"],
                    owners=[],
                    platforms=[],
                )
            ),
            ttl_seconds=3600,
        )

    with TestClient(app) as client:
        first = client.get(
            "/api/resume-review/queue",
            headers={"cookie": "hr_agent_session=admin-a-token"},
        )
        second = client.get(
            "/api/resume-review/queue",
            headers={"cookie": "hr_agent_session=admin-b-token"},
        )

    assert first.status_code == second.status_code == 200
    assert first.json()["items"] == second.json()["items"]
    assert first.json()["items"][0]["assignment"]["assignedToUserId"] == SHARED_ADMIN_INBOX


def test_admin_resume_list_includes_member_review_decisions(tmp_path: Path) -> None:
    """管理员在简历库能看到成员标记过的合适/不合适判断。"""

    app, service = _app_with_review_service(tmp_path)
    service.set_decision(
        resume_id="resume-1",
        user_id="local-member",
        decision="unsuitable",
        reason_tags=["暂不匹配"],
        note="经验不符",
    )

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        listed = client.get("/api/resumes")

    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["reviewState"]["decision"] == "undecided"
    assert item["memberReviewStates"] == [
        {
            "id": service.state_for_resume("resume-1", "local-member").id,
            "userId": "local-member",
            "userName": "历史账号（mber）",
            "resumeId": "resume-1",
            "readStatus": "viewed",
            "decision": "unsuitable",
            "reasonTags": ["暂不匹配"],
            "note": "经验不符",
            "assignedTo": "",
            "viewedAt": service.state_for_resume("resume-1", "local-member").viewed_at,
            "createdAt": service.state_for_resume("resume-1", "local-member").created_at,
            "updatedAt": service.state_for_resume("resume-1", "local-member").updated_at,
        }
    ]


def test_resume_list_omits_heavy_payload_but_detail_keeps_raw_text(
    tmp_path: Path,
) -> None:
    """List responses should stay small while detail endpoints keep full resume text."""

    database = tmp_path / "review.sqlite"
    resume_repo = ResumeRepository(database)
    raw_text = "AI product manager evidence " * 50_000
    resume_repo.save(
        Resume(
            id="resume-heavy",
            name="Heavy Candidate",
            phone="13800138001",
            education="本科",
            major="AI Product",
            job_type="AI产品经理",
            match_score=99,
            linked_owner="宋峰峰",
            linked_platform="zhilian",
            payload={
                "rawText": raw_text,
                "text": raw_text,
                "projects": [{"name": "large", "evidence": raw_text}],
                "scoreBreakdown": {"evidence": [raw_text]},
                "school": "Test University",
                "schoolLevel": "985",
                "createdAt": "2026-07-09T12:00:00+08:00",
            },
        )
    )
    review_repo = ResumeReviewRepository(database)
    app = create_app()
    app.state.resume_repository = resume_repo
    app.state.resume_service = ResumeService(resume_repo)
    app.state.resume_review_service = ResumeReviewService(
        review_repo,
        resume_repository=resume_repo,
    )
    app.state.auth_session_store_path = tmp_path / "auth_sessions.sqlite"

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        listed = client.get(
            "/api/resumes",
            params={"job_type": "AI产品经理", "sort": "score", "page_size": 10},
        )
        detail = client.get("/api/resumes/resume-heavy")
        context = client.get("/api/resumes/resume-heavy/review-context")

    assert listed.status_code == 200
    assert len(listed.content) < 200_000
    item = listed.json()["items"][0]
    assert item["id"] == "resume-heavy"
    assert item["major"] == "AI Product"
    assert item["school"] == "Test University"
    assert item["schoolLevel"] == "985"
    assert "payload" not in item
    assert "rawText" not in listed.text
    assert "scoreBreakdown" not in listed.text
    assert "projects" not in listed.text

    assert detail.status_code == 200
    assert detail.json()["payload"]["rawText"] == raw_text
    assert context.status_code == 200
    assert context.json()["resume"]["payload"]["rawText"] == raw_text


def test_gzip_middleware_compresses_large_api_responses(tmp_path: Path) -> None:
    """Large JSON responses should be gzip-compressed when browsers request it."""

    database = tmp_path / "review.sqlite"
    resume_repo = ResumeRepository(database)
    raw_text = "full detail text " * 10_000
    resume_repo.save(
        Resume(
            id="resume-gzip",
            name="GZip Candidate",
            phone="13800138002",
            job_type="AI产品经理",
            payload={"rawText": raw_text},
        )
    )
    app = create_app()
    app.state.resume_repository = resume_repo
    app.state.resume_service = ResumeService(resume_repo)
    app.state.resume_review_service = ResumeReviewService(
        ResumeReviewRepository(database),
        resume_repository=resume_repo,
    )
    app.state.auth_session_store_path = tmp_path / "auth_sessions.sqlite"

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        response = client.get(
            "/api/resumes/resume-gzip",
            headers={"Accept-Encoding": "gzip"},
        )

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"


def test_resume_file_route_returns_pdf_from_stored_resume_path(tmp_path: Path) -> None:
    """PDF 预览接口只通过简历 id 读取数据库中的文件路径。"""

    database = tmp_path / "review.sqlite"
    pdf_path = tmp_path / "resume.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% preview\n")
    resume_repo = ResumeRepository(database)
    resume_repo.save(
        Resume(
            id="resume-pdf",
            name="李四",
            phone="13900139000",
            job_type="电气工程师",
            payload={"pdfPath": str(pdf_path), "rawText": "李四 电气工程师"},
        )
    )
    app = create_app()
    app.state.resume_repository = resume_repo
    app.state.resume_service = ResumeService(resume_repo)

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        response = client.get("/api/resumes/resume-pdf/file")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["cache-control"] == "private, max-age=86400"
    assert response.headers["etag"]
    assert response.content.startswith(b"%PDF-1.4")


def test_resume_preview_image_route_renders_pdf_page(tmp_path: Path) -> None:
    """简历图片预览接口把 PDF 首页渲染成图片，避免暴露浏览器 PDF 工具栏。"""

    database = tmp_path / "review.sqlite"
    pdf_path = tmp_path / "resume.pdf"
    _write_minimal_pdf(pdf_path)
    resume_repo = ResumeRepository(database)
    resume_repo.save(
        Resume(
            id="resume-image",
            name="王五",
            phone="13700137000",
            job_type="销售管培生",
            payload={"pdfPath": str(pdf_path), "rawText": "王五 销售管培生"},
        )
    )
    app = create_app()
    app.state.resume_repository = resume_repo
    app.state.resume_service = ResumeService(resume_repo)

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        response = client.get("/api/resumes/resume-image/preview-image")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content.startswith(b"\x89PNG")


def test_resume_preview_pages_route_lists_and_renders_all_pdf_pages(tmp_path: Path) -> None:
    """Multi-page PDFs should expose page image URLs and render each requested page."""

    database = tmp_path / "review.sqlite"
    pdf_path = tmp_path / "resume-multipage.pdf"
    _write_multipage_pdf(pdf_path, page_count=2)
    resume_repo = ResumeRepository(database)
    resume_repo.save(
        Resume(
            id="resume-multipage",
            name="Multi Page",
            phone="13700137004",
            job_type="AI产品经理",
            payload={"pdfPath": str(pdf_path), "rawText": "Multi page resume"},
        )
    )
    app = create_app()
    app.state.resume_repository = resume_repo
    app.state.resume_service = ResumeService(resume_repo)

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        pages = client.get("/api/resumes/resume-multipage/preview-pages")
        first = client.get("/api/resumes/resume-multipage/preview-image?page=1")
        second = client.get("/api/resumes/resume-multipage/preview-image?page=2")
        out_of_range = client.get("/api/resumes/resume-multipage/preview-image?page=3")

    assert pages.status_code == 200
    assert pages.json() == {
        "pageCount": 2,
        "pages": [
            {"page": 1, "imageUrl": "/api/resumes/resume-multipage/preview-image?page=1"},
            {"page": 2, "imageUrl": "/api/resumes/resume-multipage/preview-image?page=2"},
        ],
    }
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content.startswith(b"\x89PNG")
    assert second.content.startswith(b"\x89PNG")
    assert first.content != second.content
    assert out_of_range.status_code == 422
    assert out_of_range.json()["detail"] == "resume_preview_page_out_of_range"


def test_resume_preview_image_cache_key_includes_pdf_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cached first page must not be reused for later PDF pages."""

    from app.api.routes import resumes as resume_routes

    database = tmp_path / "review.sqlite"
    pdf_path = tmp_path / "cached-pages.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\npages\n")
    resume_repo = ResumeRepository(database)
    resume_repo.save(
        Resume(
            id="resume-cached-pages",
            name="Cached Pages",
            phone="13700137005",
            job_type="AI产品经理",
            payload={"pdfPath": str(pdf_path), "rawText": "Cached page resume"},
        )
    )
    render_count = 0

    def fake_render_preview_image(path: Path, *, page: int = 1) -> tuple[bytes, str]:
        nonlocal render_count
        render_count += 1
        return f"png-{render_count}-page-{page}-{path.name}".encode(), "image/png"

    monkeypatch.setattr(resume_routes, "render_preview_image", fake_render_preview_image)
    app = create_app()
    app.state.resume_repository = resume_repo
    app.state.resume_service = ResumeService(resume_repo)

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        first = client.get("/api/resumes/resume-cached-pages/preview-image?page=1")
        second = client.get("/api/resumes/resume-cached-pages/preview-image?page=2")
        first_again = client.get("/api/resumes/resume-cached-pages/preview-image?page=1")
        second_again = client.get("/api/resumes/resume-cached-pages/preview-image?page=2")

    assert first.content == b"png-1-page-1-cached-pages.pdf"
    assert second.content == b"png-2-page-2-cached-pages.pdf"
    assert first_again.content == first.content
    assert second_again.content == second.content
    assert render_count == 2


def test_resume_preview_image_route_uses_disk_cache_after_memory_cache_clear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rendered PDF pages should persist on disk so repeat opens avoid rerendering."""

    from app.api.routes import resumes as resume_routes

    database = tmp_path / "review.sqlite"
    pdf_path = tmp_path / "disk-cached-resume.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\ndisk-cache\n")
    resume_repo = ResumeRepository(database)
    resume_repo.save(
        Resume(
            id="resume-disk-cached-image",
            name="Disk Cached",
            phone="13700137006",
            job_type="AI产品经理",
            payload={"pdfPath": str(pdf_path), "rawText": "Disk cached page resume"},
        )
    )
    render_count = 0

    def fake_render_preview_image(path: Path, *, page: int = 1) -> tuple[bytes, str]:
        nonlocal render_count
        render_count += 1
        return f"disk-png-{render_count}-page-{page}-{path.name}".encode(), "image/png"

    monkeypatch.setattr(resume_routes, "render_preview_image", fake_render_preview_image)
    resume_routes._PDF_PREVIEW_IMAGE_CACHE.clear()
    app = create_app()
    app.state.resume_repository = resume_repo
    app.state.resume_service = ResumeService(resume_repo)
    app.state.resume_preview_cache_dir = tmp_path / "preview-cache"

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        first = client.get("/api/resumes/resume-disk-cached-image/preview-image?page=2")
        resume_routes._PDF_PREVIEW_IMAGE_CACHE.clear()
        second = client.get("/api/resumes/resume-disk-cached-image/preview-image?page=2")

    cache_files = list((tmp_path / "preview-cache").rglob("*.png"))
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == b"disk-png-1-page-2-disk-cached-resume.pdf"
    assert second.content == first.content
    assert first.headers["etag"]
    assert "private" in first.headers["cache-control"]
    assert len(cache_files) == 1
    assert render_count == 1


def test_resume_preview_image_route_returns_not_modified_for_matching_etag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Browser cache revalidation should avoid rerendering unchanged PDF pages."""

    from app.api.routes import resumes as resume_routes

    database = tmp_path / "review.sqlite"
    pdf_path = tmp_path / "etag-resume.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\netag-cache\n")
    resume_repo = ResumeRepository(database)
    resume_repo.save(
        Resume(
            id="resume-etag-cached-image",
            name="Etag Cached",
            phone="13700137007",
            job_type="AI产品经理",
            payload={"pdfPath": str(pdf_path), "rawText": "ETag cached page resume"},
        )
    )
    render_count = 0

    def fake_render_preview_image(path: Path, *, page: int = 1) -> tuple[bytes, str]:
        nonlocal render_count
        render_count += 1
        return f"etag-png-{render_count}-page-{page}-{path.name}".encode(), "image/png"

    monkeypatch.setattr(resume_routes, "render_preview_image", fake_render_preview_image)
    resume_routes._PDF_PREVIEW_IMAGE_CACHE.clear()
    app = create_app()
    app.state.resume_repository = resume_repo
    app.state.resume_service = ResumeService(resume_repo)
    app.state.resume_preview_cache_dir = tmp_path / "preview-cache"

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        first = client.get("/api/resumes/resume-etag-cached-image/preview-image?page=1")
        revalidated = client.get(
            "/api/resumes/resume-etag-cached-image/preview-image?page=1",
            headers={"If-None-Match": first.headers["etag"]},
        )

    assert first.status_code == 200
    assert revalidated.status_code == 304
    assert revalidated.content == b""
    assert render_count == 1


def test_resume_preview_image_route_caches_pdf_render_until_file_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated PDF previews should reuse rendered PNG bytes until the source file changes."""

    from app.api.routes import resumes as resume_routes

    database = tmp_path / "review.sqlite"
    pdf_path = tmp_path / "cached-resume.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nfirst\n")
    resume_repo = ResumeRepository(database)
    resume_repo.save(
        Resume(
            id="resume-cached-image",
            name="Cached",
            phone="13700137001",
            job_type="AI产品经理",
            payload={"pdfPath": str(pdf_path), "rawText": "Cached AI product resume"},
        )
    )
    render_count = 0

    def fake_render_preview_image(path: Path) -> tuple[bytes, str]:
        nonlocal render_count
        render_count += 1
        return f"png-{render_count}-{path.name}".encode(), "image/png"

    monkeypatch.setattr(resume_routes, "render_preview_image", fake_render_preview_image)
    app = create_app()
    app.state.resume_repository = resume_repo
    app.state.resume_service = ResumeService(resume_repo)

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        first = client.get("/api/resumes/resume-cached-image/preview-image")
        second = client.get("/api/resumes/resume-cached-image/preview-image")
        pdf_path.write_bytes(b"%PDF-1.4\nchanged-and-longer\n")
        changed = client.get("/api/resumes/resume-cached-image/preview-image")

    assert first.status_code == 200
    assert second.status_code == 200
    assert changed.status_code == 200
    assert first.content == b"png-1-cached-resume.pdf"
    assert second.content == first.content
    assert changed.content == b"png-2-cached-resume.pdf"
    assert render_count == 2


def test_resume_preview_image_route_does_not_cache_non_pdf_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Image previews should keep the existing passthrough behavior."""

    from app.api.routes import resumes as resume_routes

    database = tmp_path / "review.sqlite"
    image_path = tmp_path / "resume.png"
    image_path.write_bytes(b"\x89PNG\r\nimage\n")
    resume_repo = ResumeRepository(database)
    resume_repo.save(
        Resume(
            id="resume-png-image",
            name="Image",
            phone="13700137002",
            job_type="AI产品经理",
            payload={"pdfPath": str(image_path), "rawText": "Image resume"},
        )
    )
    render_count = 0

    def fake_render_preview_image(path: Path) -> tuple[bytes, str]:
        nonlocal render_count
        render_count += 1
        return f"image-{render_count}-{path.name}".encode(), "image/png"

    monkeypatch.setattr(resume_routes, "render_preview_image", fake_render_preview_image)
    app = create_app()
    app.state.resume_repository = resume_repo
    app.state.resume_service = ResumeService(resume_repo)

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        first = client.get("/api/resumes/resume-png-image/preview-image")
        second = client.get("/api/resumes/resume-png-image/preview-image")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == b"image-1-resume.png"
    assert second.content == b"image-2-resume.png"
    assert render_count == 2


def test_resume_preview_image_route_checks_permission_before_cache_hit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cached preview must not let an unauthorized member read a hidden resume."""

    from app.api.routes import resumes as resume_routes

    database = tmp_path / "review.sqlite"
    pdf_path = tmp_path / "forbidden-resume.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nforbidden\n")
    resume_repo = ResumeRepository(database)
    resume_repo.save(
        Resume(
            id="resume-forbidden-cached-image",
            name="Forbidden",
            phone="13700137003",
            job_type="外部财务产品顾问",
            payload={"pdfPath": str(pdf_path), "rawText": "Forbidden finance resume"},
        )
    )
    render_count = 0

    def fake_render_preview_image(path: Path) -> tuple[bytes, str]:
        nonlocal render_count
        render_count += 1
        return b"cached-secret-preview", "image/png"

    monkeypatch.setattr(resume_routes, "render_preview_image", fake_render_preview_image)
    app = create_app()
    app.state.resume_repository = resume_repo
    app.state.resume_service = ResumeService(resume_repo)

    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        cached = client.get("/api/resumes/resume-forbidden-cached-image/preview-image")
        client.post("/api/auth/logout")
        client.post("/api/auth/login", json={"username": "member", "password": "member"})
        forbidden = client.get("/api/resumes/resume-forbidden-cached-image/preview-image")

    assert cached.status_code == 200
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == "resume_forbidden"
    assert render_count == 1


def _service(tmp_path: Path) -> tuple[ResumeRepository, ResumeReviewService]:
    database = tmp_path / "review.sqlite"
    resume_repo = ResumeRepository(database)
    review_repo = ResumeReviewRepository(database)
    service = ResumeReviewService(
        review_repo,
        resume_repository=resume_repo,
    )
    return resume_repo, service


def _app_with_review_service(tmp_path: Path) -> tuple[object, ResumeReviewService]:
    resume_repo, service = _service(tmp_path)
    _save_resume(resume_repo)
    app = create_app()
    app.state.resume_repository = resume_repo
    app.state.resume_service = ResumeService(resume_repo)
    app.state.resume_review_service = service
    app.state.auth_session_store_path = tmp_path / "auth_sessions.sqlite"
    return app, service


def _save_resume(repository: ResumeRepository) -> Resume:
    resume = Resume(
        id="resume-1",
        name="张三",
        phone="13800138000",
        education="本科",
        major="化工",
        job_type="AI产品经理",
        match_score=88,
        linked_owner="宋峰峰",
        linked_platform="boss",
        payload={"rawText": "张三 本科 化工 AI 产品经历"},
    )
    repository.save(resume)
    return Resume.from_record(repository.get("resume-1"))


def _write_minimal_pdf(path: Path) -> None:
    import fitz

    document = fitz.open()
    page = document.new_page(width=360, height=480)
    page.insert_text((48, 80), "Resume Preview", fontsize=18)
    document.save(path)
    document.close()


def _write_multipage_pdf(path: Path, *, page_count: int) -> None:
    import fitz

    document = fitz.open()
    for page_number in range(1, page_count + 1):
        page = document.new_page(width=360, height=480)
        page.insert_text((48, 80), f"Resume Preview Page {page_number}", fontsize=18)
    document.save(path)
    document.close()
