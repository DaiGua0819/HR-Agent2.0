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


def render_preview_image(path: Path) -> tuple[bytes, str]:
    """Render the stored preview file as browser-friendly image bytes."""

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _render_pdf_first_page(path), "image/png"
    media_type = preview_media_type(path)
    if media_type.startswith("image/"):
        return path.read_bytes(), media_type
    raise ValueError("unsupported_resume_preview_file")


def _render_pdf_first_page(path: Path) -> bytes:
    import fitz

    document = fitz.open(path)
    try:
        if document.page_count < 1:
            raise ValueError("empty_resume_pdf")
        page = document.load_page(0)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        return pixmap.tobytes("png")
    finally:
        document.close()
