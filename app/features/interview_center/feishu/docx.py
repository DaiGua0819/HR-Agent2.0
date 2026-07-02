"""Feishu Docx boundary for interview preparation."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

from app.core.dry_run import is_dry_run, record_dry_run_intent


class InterviewDocClientProtocol(Protocol):
    """Minimal document client contract for interview question packages."""

    async def create_document_from_text(self, title: str, text: str) -> dict[str, Any]:
        """Create a document from plain text and return document metadata."""


class MockInterviewDocClient:
    """Dry-run safe default document client."""

    async def create_document_from_text(self, title: str, text: str) -> dict[str, Any]:
        document_id = f"mock-doc:{uuid4()}"
        if is_dry_run():
            record_dry_run_intent("feishu.create_interview_docx", title=title)
        return {
            "documentId": document_id,
            "url": f"https://example.feishu.cn/docx/{document_id}",
            "title": title,
            "contentSynced": True,
            "contentLength": len(text),
            "dryRun": True,
        }


def build_interview_document_text(
    *,
    candidate_name: str,
    job_type: str,
    resume: dict[str, Any],
    question_set: dict[str, Any],
) -> str:
    """Build the plain-text body before the real Feishu Docx writer is wired."""

    questions = question_set.get("questions") or []
    position = job_type or resume.get("job_type") or resume.get("applied_position") or "-"
    lines = [
        f"# {candidate_name or '候选人'} 面试问题包",
        "",
        "## 候选人信息",
        f"- 姓名：{candidate_name or '-'}",
        f"- 应聘岗位：{position}",
        "",
        "## 面试问题",
    ]
    for index, item in enumerate(questions, start=1):
        lines.extend(
            [
                f"{index}. {item.get('question', '')}",
                f"   - 维度：{item.get('category', '-')}",
                f"   - 关注：{item.get('focus', '-')}",
            ]
        )
    lines.extend(["", "## 面试记录", "请在这里记录候选人的关键回答、追问结果和判断依据。"])
    return "\n".join(lines)
