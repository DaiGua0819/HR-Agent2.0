"""回归测试：live 脚本输出不能泄漏大块二进制内容。"""

from __future__ import annotations

import json

from scripts.platform_once_common import _jsonable


def test_jsonable_summarizes_bytes_payloads() -> None:
    """下载结果里的 PDF bytes 只输出摘要，不把整份简历打进终端。"""

    value = {
        "download": {
            "filename": "resume.pdf",
            "bytes": b"%PDF-1.7\n" + (b"x" * 128),
        }
    }

    result = _jsonable(value)

    assert result["download"]["bytes"] == {"type": "bytes", "length": 137}
    assert "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" not in json.dumps(result, ensure_ascii=False)
