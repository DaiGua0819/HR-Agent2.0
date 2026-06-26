"""打分规则、反馈和规则建议路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.domain.scoring.service import ScoringService, build_scoring_service

router = APIRouter(prefix="/api/scoring", tags=["scoring"])


class FeedbackRequest(BaseModel):
    """人工反馈请求。"""

    model_config = ConfigDict(populate_by_name=True)

    resume_id: str = Field(alias="resumeId")
    feedback: str


def _service(request: Request) -> ScoringService:
    service = getattr(request.app.state, "scoring_service", None)
    if service is None:
        service = build_scoring_service()
        request.app.state.scoring_service = service
    return service


@router.get("/rules")
async def get_rules(request: Request, job_type: str | None = None) -> dict[str, object]:
    """读取岗位评分规则。"""

    return _service(request).rules(job_type)


@router.post("/re-evaluate")
async def re_evaluate_resume(resume_id: str, request: Request) -> dict[str, object]:
    """重新计算单条简历评分。"""

    result = _service(request).score_resume_id(resume_id)
    if result is None:
        raise HTTPException(status_code=404, detail="resume_not_found")
    return result


@router.post("/feedback")
async def submit_feedback(payload: FeedbackRequest, request: Request) -> dict[str, object]:
    """提交反馈并生成规则建议。"""

    return _service(request).submit_feedback(payload.resume_id, payload.feedback)


@router.get("/suggestions")
async def list_suggestions(
    request: Request,
    status: str | None = None,
) -> dict[str, object]:
    """列出规则建议。"""

    return {"items": _service(request).list_suggestions(status=status)}


@router.post("/suggestions/{suggestion_id}/accept")
async def accept_suggestion(suggestion_id: str, request: Request) -> dict[str, object]:
    """采纳规则建议；本阶段只更新内存状态。"""

    result = _service(request).resolve_suggestion(suggestion_id, "accepted")
    if result is None:
        raise HTTPException(status_code=404, detail="suggestion_not_found")
    return result


@router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion(suggestion_id: str, request: Request) -> dict[str, object]:
    """拒绝规则建议；本阶段只更新内存状态。"""

    result = _service(request).resolve_suggestion(suggestion_id, "rejected")
    if result is None:
        raise HTTPException(status_code=404, detail="suggestion_not_found")
    return result
