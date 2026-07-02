"""Feishu Docx boundary for interview preparation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

import httpx

from app.core.dry_run import is_dry_run, record_dry_run_intent
from app.features.interview_center.feishu.client import (
    FEISHU_BASE_URL,
    FeishuUserTokenProvider,
)


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


@dataclass
class FeishuInterviewDocClient:
    """OAuth-backed Feishu Docx client with dry-run write protection."""

    token_provider: FeishuUserTokenProvider
    base_url: str = FEISHU_BASE_URL
    transport: httpx.AsyncBaseTransport | None = None
    dry_run: bool | None = None

    async def create_document_from_text(self, title: str, text: str) -> dict[str, Any]:
        if is_dry_run(self.dry_run):
            document_id = f"dry-run-doc:{uuid4()}"
            record_dry_run_intent("feishu.create_interview_docx", title=title)
            return {
                "documentId": document_id,
                "url": f"https://example.feishu.cn/docx/{document_id}",
                "title": title,
                "contentSynced": True,
                "contentLength": len(text),
                "dryRun": True,
            }
        user_token = await self.token_provider.user_access_token()
        if not user_token:
            raise ValueError("feishu_user_token_required")
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30,
            transport=self.transport,
        ) as client:
            created = await client.post(
                "/docx/v1/documents",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"title": title[:120]},
            )
            created.raise_for_status()
            created_payload = _feishu_payload(created.json(), "create_feishu_docx_failed")
            document = (
                created_payload.get("data", {}).get("document")
                or created_payload.get("data")
                or {}
            )
            document_id = str(
                document.get("document_id")
                or document.get("documentId")
                or document.get("obj_token")
                or ""
            )
            if not document_id:
                raise ValueError("missing_feishu_document_id")
            content_synced = False
            content_error = ""
            try:
                await _write_document_text(client, document_id, text, user_token)
                content_synced = True
            except Exception as exc:
                content_error = str(exc)
        return {
            "documentId": document_id,
            "url": document.get("url") or document.get("document_url") or f"https://feishu.cn/docx/{document_id}",
            "title": title,
            "contentSynced": content_synced,
            "contentError": content_error,
            "contentLength": len(text),
            "localText": text,
            "dryRun": False,
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


def _feishu_payload(payload: dict[str, Any], error: str) -> dict[str, Any]:
    if int(payload.get("code") or 0) != 0:
        raise ValueError(str(payload.get("msg") or error))
    return payload


async def _write_document_text(
    client: httpx.AsyncClient,
    document_id: str,
    text: str,
    user_token: str,
) -> None:
    children = _doc_text_to_blocks(text)
    if not children:
        return
    response = await client.post(
        f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
        headers={"Authorization": f"Bearer {user_token}"},
        json={"index": 0, "children": children[:100]},
    )
    response.raise_for_status()
    _feishu_payload(response.json(), "write_feishu_docx_failed")


def _doc_text_to_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for line in str(text or "").splitlines():
        content = line.strip()
        if not content:
            continue
        blocks.append(
            {
                "block_type": 2,
                "text": {
                    "elements": [
                        {
                            "text_run": {
                                "content": content[:1800],
                                "text_element_style": {},
                            }
                        }
                    ],
                    "style": {},
                },
            }
        )
    return blocks
