"""51job 真实简历下载校验与内存去重。

本阶段不接 DB；下载记忆保存在进程内存。仅接受真实附件或真实在线简历导出的
PDF/doc/docx 字节，明确拒绝聊天中的在线简历预览文字伪造 PDF。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

from app.browser.base import BrowserPage
from app.platforms.job51 import selectors
from app.platforms.types import ResumeRequestState


class ResumeByteFetcher(Protocol):
    """可 mock 的简历字节抓取接口。"""

    async def fetch(self, href: str) -> bytes:
        """按 href 抓取真实附件字节。"""


@dataclass
class InMemoryResumeDownloadMemory:
    """51job 简历下载内存桩。"""

    by_hash: dict[str, dict[str, object]] = field(default_factory=dict)

    def find_hash(self, digest: str) -> dict[str, object] | None:
        """按内容哈希查找下载记录。"""

        return self.by_hash.get(digest)

    def mark(self, digest: str, metadata: dict[str, object]) -> dict[str, object]:
        """记录已下载简历。"""

        self.by_hash[digest] = dict(metadata)
        return self.by_hash[digest]


GLOBAL_RESUME_MEMORY = InMemoryResumeDownloadMemory()


async def inspect_resume_request_state(page: BrowserPage) -> ResumeRequestState:
    """检查当前 51job 会话是否已有真实简历或已求过简历。"""

    raw = await _safe_eval_dict(page, "job51.inspect_resume_request_state")
    if not raw:
        body = await page.text()
        raw = {
            "hasResumeAttachment": "附件简历" in body or "在线简历" in body,
            "alreadyRequested": "已求简历" in body or "简历请求已发送" in body,
            "summary": body[-240:],
        }
    return ResumeRequestState(
        has_resume_attachment=bool(raw.get("hasResumeAttachment")),
        already_requested=bool(raw.get("alreadyRequested")),
        summary=str(raw.get("summary") or ""),
    )


async def request_or_download_resume(
    page: BrowserPage,
    *,
    memory: InMemoryResumeDownloadMemory | None = None,
) -> dict[str, object]:
    """优先保存真实简历；没有真实文件时回退为求简历动作。"""

    memory = memory or GLOBAL_RESUME_MEMORY
    context = await _safe_eval_dict(page, "job51.read_chat_context")
    candidate_name = str(context.get("name") or context.get("candidate_name") or "")
    position = str(context.get("position") or context.get("appliedPosition") or "")
    payload = await _safe_eval_dict(page, "job51.resume_payload")
    if payload.get("previewOnly"):
        return {"requested": True, "downloaded": False, "reason": "preview_only_rejected"}
    content = await _generic_attachment_bytes(page, payload)
    if isinstance(content, str):
        content = content.encode("utf-8")
    if isinstance(content, bytes):
        result = save_resume_bytes(
            content,
            candidate_name=candidate_name,
            applied_position=position,
            memory=memory,
        )
        if result.get("ok"):
            return {"requested": False, "resumeReceived": True, **result}
        return {"requested": True, "downloaded": False, **result}
    clicked = await _click_request_resume(page)
    return {"requested": clicked, "downloaded": False}


async def _generic_attachment_bytes(
    page: BrowserPage, payload: dict[str, object]
) -> bytes | str | None:
    """从通用真实附件来源读取字节，不带账号特判。"""

    content = payload.get("bytes")
    if content:
        return content if isinstance(content, (bytes, str)) else None
    href = str(payload.get("href") or "").strip()
    if not href or href.startswith(("blob:", "javascript:", "#")):
        return None
    fetched = await _safe_eval_dict(page, "job51.fetch_attachment_href", href)
    data = fetched.get("bytes")
    return data if isinstance(data, (bytes, str)) else None


def save_resume_bytes(
    content: bytes,
    *,
    candidate_name: str,
    applied_position: str,
    memory: InMemoryResumeDownloadMemory | None = None,
) -> dict[str, object]:
    """校验真实字节、哈希去重并写入内存下载记录。"""

    memory = memory or GLOBAL_RESUME_MEMORY
    validation = validate_resume_bytes(content)
    if not validation.ok:
        return {"ok": False, "blocked": True, "reason": validation.reason}
    guard = resume_download_suitability_guard(candidate_name, applied_position)
    if guard.get("blocked"):
        return {"ok": False, "blocked": True, "reason": guard["reason"]}
    digest = resume_content_hash(content)
    existing = memory.find_hash(digest)
    if existing:
        return {"ok": True, "duplicate": True, "fileHash": digest, "memory": existing}
    metadata = {
        "candidateName": candidate_name,
        "appliedPosition": applied_position,
        "fileHash": digest,
        "fileType": validation.file_type,
    }
    memory.mark(digest, metadata)
    return {"ok": True, "downloaded": True, "fileHash": digest, "memory": metadata}


@dataclass(frozen=True)
class ResumeValidation:
    """真实简历字节校验结果。"""

    ok: bool
    file_type: str = ""
    reason: str = ""


def validate_resume_bytes(content: bytes | bytearray | None) -> ResumeValidation:
    """校验 PDF/docx/doc 文件头，拒绝预览文字和伪 PDF。"""

    data = bytes(content or b"")
    if data.startswith(b"%PDF-") and b"%%EOF" in data[-4096:]:
        return ResumeValidation(True, "pdf")
    if data.startswith(b"PK") and b"[Content_Types].xml" in data[:4096]:
        return ResumeValidation(True, "docx")
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return ResumeValidation(True, "doc")
    return ResumeValidation(False, reason="invalid_resume_signature")


def resume_content_hash(content: bytes | bytearray | None) -> str:
    """计算简历内容哈希。"""

    return hashlib.sha256(bytes(content or b"")).hexdigest()


def resume_download_suitability_guard(
    candidate_name: str, applied_position: str
) -> dict[str, object]:
    """候选人与岗位守卫，避免无上下文文件被计为简历。"""

    if not candidate_name.strip():
        return {"blocked": True, "reason": "missing_candidate_name"}
    if not applied_position.strip():
        return {"blocked": True, "reason": "missing_applied_position"}
    return {"blocked": False}


async def _click_request_resume(page: BrowserPage) -> bool:
    for element in await page.query_all(selectors.REQUEST_RESUME_BUTTON):
        if selectors.REQUEST_RESUME_TEXT in (await element.text()):
            await element.click()
            return True
    return False


async def _safe_eval_dict(
    page: BrowserPage, script: str, arg: object | None = None
) -> dict[str, object]:
    try:
        value = await page.eval_js(script, arg)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}
