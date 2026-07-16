"""51job 简历文件校验、落盘与内存去重。

页面动作层只负责拿到真实字节；本模块负责确认它确实是 PDF/doc/docx，
并把文件保存到项目相对目录，避免把预览文字伪造成简历。
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app.settings import PROJECT_ROOT

_ANONYMOUS_NAME_SUFFIXES = ("女士", "先生", "同学", "老师")


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


@dataclass(frozen=True)
class ResumeValidation:
    """真实简历字节校验结果。"""

    ok: bool
    file_type: str = ""
    reason: str = ""


def save_resume_bytes(
    content: bytes,
    *,
    candidate_name: str,
    applied_position: str,
    filename: str = "",
    memory: InMemoryResumeDownloadMemory | None = None,
) -> dict[str, object]:
    """校验真实字节、哈希去重、落盘并写入内存下载记录。"""

    memory = memory or GLOBAL_RESUME_MEMORY
    validation = validate_resume_bytes(content)
    if not validation.ok:
        return {"ok": False, "blocked": True, "reason": validation.reason}
    guard = resume_download_suitability_guard(candidate_name, applied_position)
    if guard.get("blocked"):
        return {"ok": False, "blocked": True, "reason": guard["reason"]}
    identity = resume_identity_guard(
        bytes(content),
        candidate_name=candidate_name,
        applied_position=applied_position,
    )
    if identity.get("blocked"):
        return {"ok": False, "blocked": True, **identity}
    digest = resume_content_hash(content)
    existing = memory.find_hash(digest)
    if existing:
        return {
            "ok": True,
            "downloaded": True,
            "duplicate": True,
            "fileHash": digest,
            "filePath": str(existing.get("filePath") or ""),
            "memory": existing,
        }
    directory = PROJECT_ROOT / "data" / "downloads" / "job51"
    existing_file = _find_existing_resume_file(directory, digest)
    if existing_file is not None:
        metadata = {
            "candidateName": candidate_name,
            "appliedPosition": applied_position,
            "fileHash": digest,
            "fileType": validation.file_type,
            "filePath": str(existing_file),
        }
        memory.mark(digest, metadata)
        return {
            "ok": True,
            "downloaded": True,
            "duplicate": True,
            "fileHash": digest,
            "filePath": str(existing_file),
            "memory": metadata,
        }
    file_path = _write_resume_file(
        content,
        filename=filename,
        candidate_name=candidate_name,
        applied_position=applied_position,
        file_type=validation.file_type,
        digest=digest,
    )
    metadata = {
        "candidateName": candidate_name,
        "appliedPosition": applied_position,
        "fileHash": digest,
        "fileType": validation.file_type,
        "filePath": str(file_path),
    }
    memory.mark(digest, metadata)
    return {
        "ok": True,
        "downloaded": True,
        "fileHash": digest,
        "filePath": str(file_path),
        "memory": metadata,
    }


def validate_resume_bytes(content: bytes | bytearray | None) -> ResumeValidation:
    """校验 PDF/docx/doc 文件头，拒绝预览文字和伪 PDF。"""

    data = bytes(content or b"")
    if data.startswith(b"%PDF-") and b"%%EOF" in data[-4096:]:
        return ResumeValidation(True, "pdf")
    if data.startswith(b"PK"):
        if b"[Content_Types].xml" in data[:4096]:
            return ResumeValidation(True, "docx")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
        except (OSError, zipfile.BadZipFile):
            names = set()
        if {"[Content_Types].xml", "word/document.xml"}.issubset(names):
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


def resume_identity_guard(
    content: bytes,
    *,
    candidate_name: str,
    applied_position: str,
) -> dict[str, object]:
    """Verify downloaded PDF text belongs to the current 51job conversation."""

    text = _extract_resume_text_preview(content)
    if not text.strip():
        return {"blocked": False, "reason": "text_unavailable"}
    compact_text = _compact_text(text)
    compact_name = _compact_text(candidate_name)
    compact_position = _compact_text(applied_position)
    name_ok = bool(compact_name and compact_name in compact_text)
    position_ok = bool(compact_position and compact_position in compact_text)
    if name_ok:
        return {
            "blocked": False,
            "nameMatched": True,
            "positionMatched": position_ok,
            "matchType": "exact_name_match",
        }
    anonymous_surname = _anonymous_surname(candidate_name)
    if (
        anonymous_surname
        and position_ok
        and _anonymous_full_name_visible(text, anonymous_surname)
    ):
        return {
            "blocked": False,
            "nameMatched": False,
            "positionMatched": True,
            "matchType": "anonymous_name_resolved",
        }
    return {
        "blocked": True,
        "reason": "resume_identity_mismatch",
        "nameMatched": False,
        "positionMatched": position_ok,
        "matchType": "position_only_match" if position_ok else "identity_mismatch",
        "candidateName": candidate_name,
        "appliedPosition": applied_position,
        "textPreview": text[:300],
    }


def _write_resume_file(
    content: bytes,
    *,
    filename: str,
    candidate_name: str,
    applied_position: str,
    file_type: str,
    digest: str,
) -> Path:
    directory = PROJECT_ROOT / "data" / "downloads" / "job51"
    directory.mkdir(parents=True, exist_ok=True)
    stem = _safe_filename(
        f"51job_{candidate_name}_{applied_position}_{digest[:8]}.{file_type}"
    )
    suffix = f".{file_type}"
    if not stem.lower().endswith(suffix):
        stem = f"{stem}{suffix}"
    target = directory / stem
    if target.exists():
        target = directory / f"{target.stem}_{digest[:8]}{target.suffix}"
    target.write_bytes(content)
    return target


def _find_existing_resume_file(directory: Path, digest: str) -> Path | None:
    """跨进程查找已落盘的同内容简历，避免重复写多个副本。"""

    if not directory.exists():
        return None
    for path in directory.iterdir():
        if not path.is_file():
            continue
        try:
            if resume_content_hash(path.read_bytes()) == digest:
                return path
        except OSError:
            continue
    return None


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:120] or "resume"


def _anonymous_surname(candidate_name: str) -> str:
    compact = _compact_text(candidate_name)
    for suffix in _ANONYMOUS_NAME_SUFFIXES:
        compact_suffix = _compact_text(suffix)
        if compact.endswith(compact_suffix):
            surname = compact[: -len(compact_suffix)]
            return surname if 0 < len(surname) <= 2 else ""
    return ""


def _anonymous_full_name_visible(text: str, surname: str) -> bool:
    preview = "".join(str(text or "").split())[:400]
    if not preview or not surname:
        return False
    return bool(re.search(rf"{re.escape(surname)}[\u4e00-\u9fff]{{1,3}}", preview))


def _extract_resume_text_preview(content: bytes) -> str:
    try:
        import fitz  # type: ignore[import-not-found]
    except Exception:
        return ""
    try:
        with fitz.open(stream=content, filetype="pdf") as document:
            return "\n".join(page.get_text() for page in document[:2])
    except Exception:
        return ""


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()
