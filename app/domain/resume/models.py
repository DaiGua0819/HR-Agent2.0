"""简历领域模型。

`ResumeRecord` 保持 Phase 0 的旧库读取形态；`Resume` 是控制面 API 使用的
Pydantic 模型，字段进入模型时即完成轻量规整。两者分开可以保证读旧库不改语义，
写操作则通过内存 repository 接收规范化后的领域对象。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.resume.normalize import (
    normalize_education,
    normalize_gender,
    normalize_major,
    normalize_phone,
    normalize_position,
    normalize_resume_payload,
)
from app.domain.resume.source import infer_resume_source


@dataclass(frozen=True)
class ResumeRecord:
    """旧 SQLite 的 payload + 索引列模式。"""

    id: str
    payload: dict[str, Any]
    phone_key: str | None
    job_type: str | None
    match_score: int | None
    updated_at: str

    @property
    def candidate_name(self) -> str | None:
        """返回常见字段里的候选人姓名，供 smoke test 与列表页使用。"""

        value = self.payload.get("name") or self.payload.get("candidateName")
        return str(value) if value else None


class Resume(BaseModel):
    """控制面简历库使用的规范化模型。"""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str | None = None
    phone: str | None = None
    phone_key: str | None = None
    gender: str | None = None
    education: str | None = None
    major: str | None = None
    applied_position: str | None = None
    job_type: str | None = None
    match_score: int | None = None
    source_platform: str = "unknown"
    source_owner: str = ""
    updated_at: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("phone", "phone_key", mode="before")
    @classmethod
    def _normalize_phone(cls, value: Any) -> str | None:
        return normalize_phone(value)

    @field_validator("gender", mode="before")
    @classmethod
    def _normalize_gender(cls, value: Any) -> str | None:
        return normalize_gender(value)

    @field_validator("education", mode="before")
    @classmethod
    def _normalize_education(cls, value: Any) -> str | None:
        return normalize_education(value)

    @field_validator("major", mode="before")
    @classmethod
    def _normalize_major(cls, value: Any) -> str | None:
        return normalize_major(value)

    @field_validator("applied_position", "job_type", mode="before")
    @classmethod
    def _normalize_position(cls, value: Any) -> str | None:
        return normalize_position(value)

    @classmethod
    def from_record(cls, record: ResumeRecord) -> Resume:
        """从旧库记录构造领域模型。"""

        payload = normalize_resume_payload(record.payload)
        source = infer_resume_source(payload)
        phone = payload.get("phone") or record.phone_key
        position = payload.get("applied_position") or record.job_type
        return cls(
            id=record.id,
            name=payload.get("name") or payload.get("candidateName"),
            phone=phone,
            phone_key=record.phone_key or phone,
            gender=payload.get("gender"),
            education=payload.get("education"),
            major=payload.get("major"),
            applied_position=position,
            job_type=record.job_type or position,
            match_score=record.match_score,
            source_platform=source["platform"],
            source_owner=source["owner"],
            updated_at=record.updated_at,
            payload=payload,
        )

    def to_record(self) -> ResumeRecord:
        """转回 repository 可保存的记录形态；本阶段只写内存。"""

        payload = dict(self.payload)
        for key in ("name", "phone", "gender", "education", "major", "applied_position"):
            value = getattr(self, key)
            if value:
                payload[key] = value
        return ResumeRecord(
            id=self.id,
            payload=payload,
            phone_key=self.phone_key or self.phone,
            job_type=self.job_type or self.applied_position,
            match_score=self.match_score,
            updated_at=self.updated_at,
        )
