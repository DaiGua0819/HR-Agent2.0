"""Zhilian resume attachment validation and local storage."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.platforms.job51.resume_files import (
    ResumeValidation,
    resume_content_hash,
    resume_download_suitability_guard,
    validate_resume_bytes,
)
from app.settings import PROJECT_ROOT


@dataclass
class InMemoryZhilianResumeMemory:
    """In-process memory for Zhilian resume downloads."""

    by_hash: dict[str, dict[str, object]] = field(default_factory=dict)

    def find_hash(self, digest: str) -> dict[str, object] | None:
        """Return an existing download record by content hash."""

        return self.by_hash.get(digest)

    def mark(self, digest: str, metadata: dict[str, object]) -> dict[str, object]:
        """Remember a downloaded resume in process memory."""

        self.by_hash[digest] = dict(metadata)
        return self.by_hash[digest]


GLOBAL_ZHILIAN_RESUME_MEMORY = InMemoryZhilianResumeMemory()


def save_zhilian_resume_bytes(
    content: bytes,
    *,
    candidate_name: str,
    applied_position: str,
    filename: str = "",
    memory: InMemoryZhilianResumeMemory | None = None,
) -> dict[str, object]:
    """Validate and save real Zhilian resume bytes under data/downloads/zhilian."""

    memory = memory or GLOBAL_ZHILIAN_RESUME_MEMORY
    validation = validate_resume_bytes(content)
    if not validation.ok:
        return {"ok": False, "blocked": True, "reason": validation.reason}
    guard = resume_download_suitability_guard(candidate_name, applied_position)
    if guard.get("blocked"):
        return {"ok": False, "blocked": True, "reason": guard["reason"]}
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
    directory = PROJECT_ROOT / "data" / "downloads" / "zhilian"
    existing_file = _find_existing_resume_file(directory, digest)
    if existing_file is not None:
        metadata = _metadata(
            candidate_name,
            applied_position,
            digest,
            validation,
            existing_file,
        )
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
    metadata = _metadata(candidate_name, applied_position, digest, validation, file_path)
    memory.mark(digest, metadata)
    return {
        "ok": True,
        "downloaded": True,
        "fileHash": digest,
        "filePath": str(file_path),
        "memory": metadata,
    }


def _metadata(
    candidate_name: str,
    applied_position: str,
    digest: str,
    validation: ResumeValidation,
    file_path: Path,
) -> dict[str, object]:
    return {
        "candidateName": candidate_name,
        "appliedPosition": applied_position,
        "fileHash": digest,
        "fileType": validation.file_type,
        "filePath": str(file_path),
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
    directory = PROJECT_ROOT / "data" / "downloads" / "zhilian"
    directory.mkdir(parents=True, exist_ok=True)
    stem = _safe_filename(
        filename
        or f"zhilian_{candidate_name}_{applied_position}_{digest[:8]}.{file_type}"
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
