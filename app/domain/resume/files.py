"""Resolve stored resume files for safe preview by resume id."""

from __future__ import annotations

from pathlib import Path

from app.domain.resume.models import Resume

_PATH_KEYS = (
    "pdfPath",
    "pdf_path",
    "filePath",
    "file_path",
    "localPath",
    "local_path",
    "downloadPath",
    "download_path",
    "sourceFile",
    "source_file",
)
_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def preview_file_path(resume: Resume) -> Path | None:
    """Return an existing previewable file path stored on the resume payload."""

    for key in _PATH_KEYS:
        value = resume.payload.get(key)
        if not value:
            continue
        path = Path(str(value))
        if path.is_file() and preview_media_type(path):
            return path
    return None


def preview_media_type(path: Path) -> str:
    """Return the media type for a supported preview file."""

    return _MEDIA_TYPES.get(path.suffix.lower(), "")


def has_preview_file(resume: Resume) -> bool:
    """Return whether the resume has a stored PDF/image preview file."""

    return preview_file_path(resume) is not None


def preview_page_count(path: Path) -> int:
    """Return the number of preview pages for a stored resume file."""

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_page_count(path)
    media_type = preview_media_type(path)
    if media_type.startswith("image/"):
        return 1
    raise ValueError("unsupported_resume_preview_file")


def render_preview_image(path: Path, *, page: int = 1) -> tuple[bytes, str]:
    """Render the stored preview file as browser-friendly image bytes."""

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _render_pdf_page(path, page=page), "image/png"
    if page != 1:
        raise ValueError("resume_preview_page_out_of_range")
    media_type = preview_media_type(path)
    if media_type.startswith("image/"):
        return path.read_bytes(), media_type
    raise ValueError("unsupported_resume_preview_file")


def _pdf_page_count(path: Path) -> int:
    import fitz

    document = fitz.open(path)
    try:
        if document.page_count < 1:
            raise ValueError("empty_resume_pdf")
        return int(document.page_count)
    finally:
        document.close()


def _render_pdf_page(path: Path, *, page: int) -> bytes:
    import fitz

    if page < 1:
        raise ValueError("resume_preview_page_out_of_range")
    document = fitz.open(path)
    try:
        if document.page_count < 1:
            raise ValueError("empty_resume_pdf")
        if page > document.page_count:
            raise ValueError("resume_preview_page_out_of_range")
        pdf_page = document.load_page(page - 1)
        pixmap = pdf_page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        return pixmap.tobytes("png")
    finally:
        document.close()
