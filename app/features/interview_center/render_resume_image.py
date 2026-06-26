"""简历 PDF 渲染为图片。

直接承接旧独立 Python 脚本职责：用 PyMuPDF 读取 PDF 页面并输出 PNG。函数既可返回 bytes，
也可写入目标路径，方便 API 上传和测试真测。
"""

from __future__ import annotations

from pathlib import Path


def render_resume_image(
    pdf_path: str | Path,
    output_path: str | Path | None = None,
    *,
    page_index: int = 0,
    zoom: float = 2.0,
) -> bytes:
    """把 PDF 指定页渲染为 PNG bytes。"""

    import fitz

    source = Path(pdf_path)
    if not source.exists():
        raise FileNotFoundError(source)
    with fitz.open(source) as document:
        if document.page_count == 0:
            raise ValueError("empty_pdf")
        page = document.load_page(page_index)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image_bytes = pixmap.tobytes("png")
    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image_bytes)
    return image_bytes
