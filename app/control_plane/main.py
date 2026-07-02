"""控制面 FastAPI 应用装配。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.auth import router as auth_router
from app.api.routes.automation import router as automation_router
from app.api.routes.batch import router as batch_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.email_import import router as email_import_router
from app.api.routes.health import router as health_router
from app.api.routes.interview import router as interview_router
from app.api.routes.monitoring import router as monitoring_router
from app.api.routes.resume_review import router as resume_review_router
from app.api.routes.resumes import router as resumes_router
from app.api.routes.scoring import router as scoring_router
from app.control_plane.dispatcher import Dispatcher
from app.domain.batch.service import BatchService
from app.domain.email_import.service import GLOBAL_EMAIL_IMPORT_SERVICE
from app.domain.resume.repository import ResumeRepository
from app.domain.resume.service import ResumeService
from app.domain.resume_review.repository import ResumeReviewRepository
from app.domain.resume_review.service import ResumeReviewService
from app.domain.scoring.service import ScoringService
from app.features.interview_center.service import InterviewCenterService
from app.settings import PROJECT_ROOT, load_settings


def create_app(dispatcher: Dispatcher | None = None) -> FastAPI:
    """创建控制面应用。"""

    settings = load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.interview_center_service.start_schedulers()
        try:
            yield
        finally:
            await app.state.interview_center_service.stop_schedulers()

    app = FastAPI(title="HR Agent Control Plane", lifespan=lifespan)
    repository = ResumeRepository.from_settings()
    scoring_service = ScoringService(repository)
    review_repository = ResumeReviewRepository(settings.resolved_database_path)

    app.state.dispatcher = dispatcher or Dispatcher()
    app.state.resume_repository = repository
    app.state.scoring_service = scoring_service
    app.state.resume_service = ResumeService(repository, scoring_service=scoring_service)
    app.state.resume_review_service = ResumeReviewService(
        review_repository,
        resume_repository=repository,
    )
    app.state.batch_service = BatchService()
    app.state.email_import_service = GLOBAL_EMAIL_IMPORT_SERVICE
    app.state.interview_center_service = InterviewCenterService(repository=repository)

    app.include_router(auth_router)
    app.include_router(health_router)
    app.include_router(dashboard_router)
    app.include_router(automation_router)
    app.include_router(resumes_router)
    app.include_router(resume_review_router)
    app.include_router(scoring_router)
    app.include_router(batch_router)
    app.include_router(email_import_router)
    app.include_router(monitoring_router)
    app.include_router(interview_router)

    frontend_dir = PROJECT_ROOT / "frontend"
    if frontend_dir.exists():
        app.mount("/assets", StaticFiles(directory=frontend_dir), name="frontend-assets")

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(_frontend_file("index.html"))

    @app.get("/index.html")
    async def index() -> FileResponse:
        return FileResponse(_frontend_file("index.html"))

    @app.get("/app/{path:path}")
    async def app_entry(path: str) -> FileResponse:
        return FileResponse(_frontend_file("index.html"))

    return app


def _frontend_file(filename: str) -> Path:
    return PROJECT_ROOT / "frontend" / filename
