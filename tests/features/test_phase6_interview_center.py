"""Phase 6：面试中心测试。

飞书使用 mock，LLM 使用假实现，出图脚本真实生成 PNG，不连接真实 DB/浏览器/飞书。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import fitz
from app.control_plane.main import create_app
from app.domain.resume.models import ResumeRecord
from app.domain.resume.repository import ResumeRepository
from app.features.interview_center.candidate_matcher import match_candidates
from app.features.interview_center.feishu.assets import BITABLE_TABLES
from app.features.interview_center.feishu.bitable import MockFeishuBitableClient
from app.features.interview_center.question_generator import InterviewQuestionGenerator
from app.features.interview_center.render_resume_image import render_resume_image
from app.features.interview_center.service import InterviewCenterService
from app.features.interview_center.store import InMemoryInterviewStore
from fastapi.testclient import TestClient
from PIL import Image


def test_candidate_matcher_scores_phone_name_and_position() -> None:
    """候选人匹配优先手机号，其次姓名和岗位。"""

    matches = match_candidates(
        {"name": "Alice", "phone": "13800138000", "job_type": "电气工程师"},
        [
            {"name": "Alice", "phone": "13800138000", "job_type": "电气工程师"},
            {"name": "Bob", "phone": "13900139000", "job_type": "销售管培生"},
        ],
    )
    assert matches[0]["score"] == 100
    assert "phone_exact" in matches[0]["reasons"]
    assert len(matches) == 1


def test_question_generator_parses_fake_llm_response() -> None:
    """假 LLM 返回 JSON 时，出题结构保持 category/question/focus。"""

    generator = InterviewQuestionGenerator(FakeLLM())
    questions = asyncio.run(
        generator.generate(
            resume={"name": "Alice", "rawText": "Python LLM Agent 项目"},
            job_type="AI应用开发实习生",
            conversation=[],
        )
    )
    assert questions == [
        {"category": "项目", "question": "请介绍 Agent 项目。", "focus": "项目真实性"}
    ]


def test_render_resume_image_generates_png_from_sample_pdf(tmp_path: Path) -> None:
    """PyMuPDF 真测：样例 PDF 可渲染为 PNG 且尺寸合理。"""

    pdf_path = tmp_path / "resume.pdf"
    png_path = tmp_path / "resume.png"
    _write_sample_pdf(pdf_path)

    image_bytes = render_resume_image(pdf_path, png_path)
    assert image_bytes.startswith(b"\x89PNG")
    assert png_path.exists()
    with Image.open(png_path) as image:
        assert image.width >= 300
        assert image.height >= 200


def test_interview_orchestration_uses_mock_feishu_fake_llm_and_images(tmp_path: Path) -> None:
    """主流程跑通：简历→出题→bitable mock 同步→出图→会话状态。"""

    pdf_path = tmp_path / "resume.pdf"
    _write_sample_pdf(pdf_path)
    bitable = MockFeishuBitableClient(
        records={
            BITABLE_TABLES.candidates: [
                {
                    "record_id": "cand-1",
                    "fields": {
                        "name": "Alice",
                        "phone": "13800138000",
                        "job_type": "AI应用开发实习生",
                    },
                }
            ]
        }
    )
    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=InMemoryInterviewStore(),
        bitable=bitable,
        llm=FakeLLM(),
        output_dir=tmp_path,
    )

    result = asyncio.run(
        service.create_session_from_resume(
            "resume-1",
            conversation=[{"sender": "candidate", "text": "做过 Agent 项目"}],
            resume_pdf_path=str(pdf_path),
            dry_run=True,
        )
    )
    session = result["session"]
    assert session["status"] == "ready"
    assert session["questions"][0]["question"] == "请介绍 Agent 项目。"
    assert Path(session["resumeImagePath"]).exists()
    assert Path(session["summaryImagePath"]).exists()
    assert any(call["method"] == "create_record" for call in bitable.calls)
    assert any(call["method"] == "upload_file" for call in bitable.calls)

    backfill = asyncio.run(
        service.backfill_feedback(
            session["id"],
            result="pass",
            feedback="项目扎实",
            interviewer="HR",
        )
    )
    assert backfill["session"]["feedback"] == "项目扎实"


def test_feishu_mock_bitable_crud_contract() -> None:
    """mock bitable 覆盖 list/create/update/upload 调用契约。"""

    client = MockFeishuBitableClient()

    async def run_case() -> None:
        created = await client.create_record("table", {"姓名": "Alice"})
        listed = await client.list_records("table")
        updated = await client.update_record("table", created["record_id"], {"状态": "ready"})
        token = await client.upload_file("summary.png")
        assert listed[0]["fields"]["姓名"] == "Alice"
        assert updated["fields"]["状态"] == "ready"
        assert token == "mock-file-token:summary.png"

    asyncio.run(run_case())


def test_interview_center_api_routes_are_wired(tmp_path: Path) -> None:
    """控制面挂载面试中心 API，服务可通过 app.state 注入 mock。"""

    service = InterviewCenterService(
        repository=ResumeRepository.in_memory([_resume_record()]),
        store=InMemoryInterviewStore(),
        bitable=MockFeishuBitableClient(),
        llm=FakeLLM(),
        output_dir=tmp_path,
    )
    app = create_app()
    app.state.interview_center_service = service
    with TestClient(app) as client:
        invite = client.post("/api/interview/invite", json={"resumeId": "resume-1", "dryRun": True})
        assert invite.json()["accepted"] is True

        created = client.post(
            "/api/interview-center/sessions",
            json={
                "resume": {
                    "id": "payload-1",
                    "name": "Alice",
                    "phone": "13800138000",
                    "job_type": "AI应用开发实习生",
                    "rawText": "Python Agent",
                },
                "conversation": [],
            },
        )
        assert created.status_code == 200
        session_id = created.json()["session"]["id"]

        listed = client.get("/api/interview-center/sessions")
        assert listed.json()["items"][0]["id"] == session_id

        feedback = client.post(
            f"/api/interview-center/sessions/{session_id}/feedback-backfill",
            json={"result": "pass", "feedback": "OK", "interviewer": "HR"},
        )
        assert feedback.json()["session"]["status"] == "pass"


class FakeLLM:
    """测试用出题 LLM。"""

    async def chat_completions(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        _ = messages, temperature
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            [
                                {
                                    "category": "项目",
                                    "question": "请介绍 Agent 项目。",
                                    "focus": "项目真实性",
                                }
                            ],
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }


def _resume_record() -> ResumeRecord:
    return ResumeRecord(
        id="resume-1",
        payload={
            "name": "Alice",
            "phone": "13800138000",
            "job_type": "AI应用开发实习生",
            "rawText": "Alice 13800138000 Python LLM Agent 项目",
        },
        phone_key="13800138000",
        job_type="AI应用开发实习生",
        match_score=90,
        updated_at="2026-01-01",
    )


def _write_sample_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=420, height=300)
    page.insert_text((72, 72), "Sample Resume - Alice")
    page.insert_text((72, 110), "Python / LLM / Agent")
    document.save(path)
    document.close()
