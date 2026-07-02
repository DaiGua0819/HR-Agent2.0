"""飞书多维表记录与素材接口。

真实 HTTP 适配器也受全局 dry-run 保护：写记录、更新记录、上传文件只记录意图，
不会触碰真实飞书。测试使用 `MockFeishuBitableClient`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import httpx

from app.core.dry_run import is_dry_run, record_dry_run_intent
from app.core.text import clean_text
from app.domain.resume.normalize import normalize_phone
from app.features.interview_center.feishu.client import FeishuAuthClient, FeishuTokenProvider
from app.settings import FeishuConfig, load_settings


@dataclass(frozen=True)
class ExistingBitableRecord:
    """Result of matching a resume to an existing Bitable record."""

    record: dict[str, Any] | None
    reason: str
    count: int = 0

    @property
    def record_id(self) -> str:
        """Return the Feishu record id when a record was matched."""

        if not self.record:
            return ""
        return str(self.record.get("record_id") or self.record.get("id") or "")


class BitableClientProtocol(Protocol):
    """面试中心需要的 bitable 能力。"""

    async def list_records(self, table_id: str) -> list[dict[str, Any]]:
        """列出记录。"""

    async def create_record(self, table_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """新增记录。"""

    async def update_record(
        self,
        table_id: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """更新记录。"""

    async def upload_file(self, file_path: str | Path) -> str:
        """上传素材并返回 token。"""


@dataclass
class FeishuBitableClient:
    """真实飞书多维表 HTTP 客户端。"""

    token_provider: FeishuTokenProvider | None = None
    config: FeishuConfig | None = None
    base_url: str = "https://open.feishu.cn/open-apis"

    def __post_init__(self) -> None:
        self.config = self.config or load_settings().feishu
        self.token_provider = self.token_provider or FeishuAuthClient(self.config)

    async def list_records(self, table_id: str) -> list[dict[str, Any]]:
        """读取多维表记录。"""

        assert self.config is not None
        url = f"/bitable/v1/apps/{self.config.bitable_app_token}/tables/{table_id}/records"
        data = await self._request("GET", url)
        return list(data.get("data", {}).get("items", []))

    async def create_record(self, table_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """新增多维表记录。"""

        if is_dry_run():
            record_dry_run_intent("feishu.create_record", tableId=table_id, fields=fields)
            return {"record_id": f"dry-run:{uuid4()}", "fields": dict(fields), "dryRun": True}
        assert self.config is not None
        url = f"/bitable/v1/apps/{self.config.bitable_app_token}/tables/{table_id}/records"
        return await self._request("POST", url, json={"fields": fields})

    async def update_record(
        self,
        table_id: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """更新多维表记录。"""

        if is_dry_run():
            record_dry_run_intent(
                "feishu.update_record",
                tableId=table_id,
                recordId=record_id,
                fields=fields,
            )
            return {"record_id": record_id, "fields": dict(fields), "dryRun": True}
        assert self.config is not None
        url = (
            f"/bitable/v1/apps/{self.config.bitable_app_token}/tables/{table_id}"
            f"/records/{record_id}"
        )
        return await self._request("PUT", url, json={"fields": fields})

    async def upload_file(self, file_path: str | Path) -> str:
        """上传文件；真实 multipart 细节最后阶段联调。"""

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(path)
        if is_dry_run():
            record_dry_run_intent("feishu.upload_file", filePath=str(path))
            return f"dry-run-file-token:{path.name}"
        return f"pending-real-upload:{path.name}"

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        assert self.token_provider is not None
        headers = {"Authorization": f"Bearer {await self.token_provider.tenant_access_token()}"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30, headers=headers) as client:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
        return response.json()


@dataclass
class MockFeishuBitableClient:
    """内存 mock：记录 CRUD 调用契约，不触碰真实飞书。"""

    records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    uploaded_files: list[str] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def list_records(self, table_id: str) -> list[dict[str, Any]]:
        self.calls.append({"method": "list_records", "tableId": table_id})
        return list(self.records.get(table_id, []))

    async def create_record(self, table_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"method": "create_record", "tableId": table_id, "fields": fields})
        record = {"record_id": str(uuid4()), "fields": dict(fields)}
        self.records.setdefault(table_id, []).append(record)
        return record

    async def update_record(
        self,
        table_id: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "method": "update_record",
                "tableId": table_id,
                "recordId": record_id,
                "fields": fields,
            }
        )
        for record in self.records.setdefault(table_id, []):
            if record.get("record_id") == record_id:
                record.setdefault("fields", {}).update(fields)
                return record
        record = {"record_id": record_id, "fields": dict(fields)}
        self.records[table_id].append(record)
        return record

    async def upload_file(self, file_path: str | Path) -> str:
        path = Path(file_path)
        token = f"mock-file-token:{path.name}"
        self.calls.append({"method": "upload_file", "filePath": str(path), "token": token})
        self.uploaded_files.append(str(path))
        return token


def find_existing_bitable_record(
    records: list[dict[str, Any]],
    resume: dict[str, Any],
) -> ExistingBitableRecord:
    """Match an existing Bitable record by phone first, then by unique exact name."""

    phone = normalize_phone(
        resume.get("phone")
        or resume.get("phone_key")
        or resume.get("candidatePhone")
        or resume.get("candidate_phone")
    )
    if phone:
        by_phone = next(
            (
                record
                for record in records
                if _field_contains_phone(
                    record.get("fields", {}).get("候选人联系电话"),
                    phone,
                )
            ),
            None,
        )
        if by_phone:
            return ExistingBitableRecord(record=by_phone, reason="phone_match")

    name = _normalize_match_text(
        resume.get("name") or resume.get("candidateName") or resume.get("candidate_name")
    )
    if not name:
        return ExistingBitableRecord(record=None, reason="missing_name")
    name_matches = [
        record
        for record in records
        if any(
            _normalize_match_text(_extract_field_text(value)) == name
            for value in (
                record.get("fields", {}).get("姓名"),
                record.get("fields", {}).get("候选人姓名"),
            )
        )
    ]
    if len(name_matches) == 1:
        return ExistingBitableRecord(record=name_matches[0], reason="name_match")
    if len(name_matches) > 1:
        return ExistingBitableRecord(
            record=None,
            reason="ambiguous_name_match",
            count=len(name_matches),
        )
    return ExistingBitableRecord(record=None, reason="not_found")


def pick_existing_bitable_fields(
    fields: dict[str, Any],
    field_map: Any,
) -> dict[str, Any]:
    """Keep only non-empty fields that exist in the target Bitable field map."""

    existing_names = _field_names(field_map)
    result: dict[str, Any] = {}
    for name, value in fields.items():
        if value is None or value == "":
            continue
        if name not in existing_names:
            continue
        result[name] = value
    return result


def _field_contains_phone(value: Any, phone: str) -> bool:
    field_text = _extract_field_text(value)
    normalized = normalize_phone(field_text)
    if normalized == phone:
        return True
    digits = "".join(ch for ch in clean_text(field_text) if ch.isdigit())
    return bool(digits and phone in digits)


def _extract_field_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str | int | float):
        return str(value)
    if isinstance(value, list | tuple | set):
        return " ".join(_extract_field_text(item) for item in value if _extract_field_text(item))
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("text", "name", "email", "id", "link", "url"):
            if value.get(key) not in (None, ""):
                parts.append(str(value[key]))
        text_arr = value.get("text_arr")
        if isinstance(text_arr, list):
            parts.append(_extract_field_text(text_arr))
        return " ".join(part for part in parts if part)
    return str(value)


def _normalize_match_text(value: Any) -> str:
    return clean_text(value).lower()


def _field_names(field_map: Any) -> set[str]:
    if field_map is None:
        return set()
    by_name = getattr(field_map, "by_name", None) or getattr(field_map, "byName", None)
    if by_name is not None:
        return set(_mapping_keys(by_name))
    if isinstance(field_map, dict):
        by_name = field_map.get("byName") or field_map.get("by_name")
        if by_name is not None:
            return set(_mapping_keys(by_name))
        items = field_map.get("items")
        if isinstance(items, list):
            return set(_field_name_from_item(item) for item in items if _field_name_from_item(item))
    if isinstance(field_map, list):
        return set(_field_name_from_item(item) for item in field_map if _field_name_from_item(item))
    return set()


def _mapping_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [str(key) for key in value]
    keys = getattr(value, "keys", None)
    if callable(keys):
        return [str(key) for key in keys()]
    return []


def _field_name_from_item(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("field_name") or item.get("name") or "")
    return str(getattr(item, "field_name", "") or getattr(item, "name", "") or "")
