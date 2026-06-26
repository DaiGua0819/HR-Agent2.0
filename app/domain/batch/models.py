"""批量解析任务模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def now_iso() -> str:
    """返回 ISO 时间字符串。"""

    return datetime.now(UTC).isoformat()


@dataclass
class BatchItem:
    """批量任务明细。"""

    id: str
    job_id: str
    file_name: str
    file_path: str = ""
    status: str = "pending"
    payload: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    resume_id: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 API 响应。"""

        return {
            "id": self.id,
            "jobId": self.job_id,
            "fileName": self.file_name,
            "filePath": self.file_path,
            "status": self.status,
            "payload": self.payload,
            "error": self.error,
            "resumeId": self.resume_id,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass
class BatchJob:
    """批量简历解析任务。"""

    id: str
    parse_mode: str
    status: str = "pending"
    items: list[BatchItem] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 API 响应。"""

        total = len(self.items)
        done = len([item for item in self.items if item.status == "done"])
        failed = len([item for item in self.items if item.status == "failed"])
        return {
            "id": self.id,
            "parseMode": self.parse_mode,
            "status": self.status,
            "total": total,
            "done": done,
            "failed": failed,
            "items": [item.to_dict() for item in self.items],
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
