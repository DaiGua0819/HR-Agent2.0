"""控制面 FastAPI 应用装配。"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.routes.automation import router as automation_router
from app.api.routes.batch import router as batch_router
from app.api.routes.email_import import router as email_import_router
from app.api.routes.health import router as health_router
from app.api.routes.interview import router as interview_router
from app.api.routes.monitoring import router as monitoring_router
from app.api.routes.resumes import router as resumes_router
from app.api.routes.scoring import router as scoring_router
from app.control_plane.dispatcher import Dispatcher
from app.domain.batch.service import BatchService
from app.domain.email_import.service import GLOBAL_EMAIL_IMPORT_SERVICE
from app.domain.resume.repository import ResumeRepository
from app.domain.resume.service import ResumeService
from app.domain.scoring.service import ScoringService
from app.features.interview_center.service import InterviewCenterService
from app.settings import load_settings


def create_app(dispatcher: Dispatcher | None = None) -> FastAPI:
    """创建控制面应用。"""

    settings = load_settings()
    app = FastAPI(title="HR Agent Control Plane")
    repository = ResumeRepository.from_settings()
    scoring_service = ScoringService(repository)

    app.state.dispatcher = dispatcher or Dispatcher()
    app.state.resume_repository = repository
    app.state.scoring_service = scoring_service
    app.state.resume_service = ResumeService(repository, scoring_service=scoring_service)
    app.state.batch_service = BatchService()
    app.state.email_import_service = GLOBAL_EMAIL_IMPORT_SERVICE
    app.state.interview_center_service = InterviewCenterService(repository=repository)

    app.include_router(health_router)
    app.include_router(automation_router)
    app.include_router(resumes_router)
    app.include_router(scoring_router)
    app.include_router(batch_router)
    app.include_router(email_import_router)
    app.include_router(monitoring_router)
    app.include_router(interview_router)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {"service": settings.app_name, "status": "ok"}

    return app
