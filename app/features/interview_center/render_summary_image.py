"""面试小结渲染为图片。

移植旧 `render_interview_summary_image.py` 的职责：将候选人、岗位、问题和反馈摘要绘制成
PNG。使用 Pillow，真实生成文件但不上传外部系统。
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any


def render_summary_image(
    session: dict[str, Any] | str,
    output_path: str | Path | None = None,
    *,
    width: int = 1000,
) -> bytes:
    """把面试会话摘要渲染成 PNG bytes。"""

    from io import BytesIO

    from PIL import Image, ImageDraw, ImageFont

    data = {"sessionId": session} if isinstance(session, str) else session
    lines = _summary_lines(data)
    line_height = 30
    height = max(420, 80 + len(lines) * line_height)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()

    draw.rectangle((0, 0, width, 56), fill=(29, 78, 216))
    _draw_text(draw, (32, 20), "Interview Summary", fill="white", font=font)
    y = 82
    for line in lines:
        _draw_text(draw, (32, y), line, fill=(31, 41, 55), font=font)
        y += line_height

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    image_bytes = buffer.getvalue()
    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image_bytes)
    return image_bytes


def _summary_lines(session: dict[str, Any]) -> list[str]:
    questions = session.get("questions") or []
    if isinstance(questions, list):
        question_text = " / ".join(
            str(item.get("question", item)) if isinstance(item, dict) else str(item)
            for item in questions[:5]
        )
    else:
        question_text = str(questions)
    raw_lines = [
        f"Session: {session.get('id') or session.get('sessionId') or ''}",
        f"Candidate: {session.get('candidateName') or session.get('name') or ''}",
        f"Position: {session.get('jobType') or session.get('position') or ''}",
        f"Status: {session.get('status') or ''}",
        f"Questions: {question_text}",
        f"Feedback: {session.get('feedback') or ''}",
    ]
    lines: list[str] = []
    for line in raw_lines:
        lines.extend(textwrap.wrap(line, width=110) or [""])
    return lines


def _draw_text(draw: Any, xy: tuple[int, int], text: str, *, fill: Any, font: Any) -> None:
    """默认字体不支持中文时降级，保证图片真测不失败。"""

    try:
        draw.text(xy, text, fill=fill, font=font)
    except UnicodeEncodeError:
        safe = text.encode("ascii", errors="replace").decode("ascii")
        draw.text(xy, safe, fill=fill, font=font)
