"""简历文件存取与真实文件头校验。

保留 51job 伪简历教训：PDF 必须 `%PDF-`，docx 必须 `PK`，doc 必须 OLE 头。
"""

from __future__ import annotations

from pathlib import Path

DOC_OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")


def detect_resume_file_type(path: str | Path) -> str | None:
    """按文件头识别真实简历类型。"""

    with Path(path).open("rb") as file:
        header = file.read(8)
    if header.startswith(b"%PDF-"):
        return "pdf"
    if header.startswith(b"PK"):
        return "docx"
    if header.startswith(DOC_OLE_MAGIC):
        return "doc"
    return None


def assert_real_resume_file(path: str | Path) -> None:
    """校验真实简历文件头，不接受在线预览文本伪装。"""

    if detect_resume_file_type(path) is None:
        raise ValueError(f"不是真实简历文件: {path}")
