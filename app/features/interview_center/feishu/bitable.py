"""飞书多维表记录与素材接口。

真实 HTTP 适配器也受全局 dry-run 保护：写记录、更新记录、上传文件只记录意图，
不会触碰真实飞书。测试使用 `MockFeishuBitableClient`。
"""

from __future__ import annotations

import mimetypes
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
    transport: httpx.AsyncBaseTransport | None = None
    dry_run: bool | None = None
    _fields_cache: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.config = self.config or load_settings().feishu
        self.token_provider = self.token_provider or FeishuAuthClient(self.config)

    async def list_records(self, table_id: str) -> list[dict[str, Any]]:
        """读取多维表记录。"""

        self._assert_bitable_configured()
        records: list[dict[str, Any]] = []
        page_token = ""
        while True:
            data = await self._request(
                "GET",
                f"{self._table_url(table_id)}/records",
                params={
                    "page_size": "500",
                    "user_id_type": "open_id",
                    **({"page_token": page_token} if page_token else {}),
                },
            )
            payload = data.get("data") or {}
            records.extend(list(payload.get("items") or []))
            page_token = str(payload.get("page_token") or "")
            if not payload.get("has_more") or not page_token:
                break
        return records

    async def list_fields(self, table_id: str, *, force: bool = False) -> dict[str, Any]:
        """读取并缓存多维表字段，用于写入前过滤不存在字段。"""

        if table_id in self._fields_cache and not force:
            return self._fields_cache[table_id]
        self._assert_bitable_configured()
        fields: list[dict[str, Any]] = []
        page_token = ""
        while True:
            data = await self._request(
                "GET",
                f"{self._table_url(table_id)}/fields",
                params={
                    "page_size": "100",
                    **({"page_token": page_token} if page_token else {}),
                },
            )
            payload = data.get("data") or {}
            fields.extend(list(payload.get("items") or []))
            page_token = str(payload.get("page_token") or "")
            if not payload.get("has_more") or not page_token:
                break
        field_map = {
            "items": fields,
            "byName": {
                str(field.get("field_name") or field.get("name") or ""): field
                for field in fields
                if field.get("field_name") or field.get("name")
            },
        }
        self._fields_cache[table_id] = field_map
        return field_map

    async def create_record(self, table_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """新增多维表记录。"""

        if is_dry_run(self.dry_run):
            record_dry_run_intent("feishu.create_record", tableId=table_id, fields=fields)
            return {"record_id": f"dry-run:{uuid4()}", "fields": dict(fields), "dryRun": True}
        field_map = await self.list_fields(table_id)
        data = await self._request(
            "POST",
            f"{self._table_url(table_id)}/records",
            params={"user_id_type": "open_id"},
            json={"fields": pick_existing_bitable_fields(fields, field_map)},
        )
        return data.get("data", {}).get("record") or data.get("data") or {}

    async def update_record(
        self,
        table_id: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """更新多维表记录。"""

        if is_dry_run(self.dry_run):
            record_dry_run_intent(
                "feishu.update_record",
                tableId=table_id,
                recordId=record_id,
                fields=fields,
            )
            return {"record_id": record_id, "fields": dict(fields), "dryRun": True}
        if not record_id:
            return await self.create_record(table_id, fields)
        field_map = await self.list_fields(table_id)
        data = await self._request(
            "PUT",
            f"{self._table_url(table_id)}/records/{record_id}",
            params={"user_id_type": "open_id"},
            json={"fields": pick_existing_bitable_fields(fields, field_map)},
        )
        return data.get("data", {}).get("record") or data.get("data") or {}

    async def upload_file(self, file_path: str | Path) -> str:
        """上传文件到飞书 Drive，供 Bitable 附件字段引用。"""

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(path)
        if is_dry_run(self.dry_run):
            record_dry_run_intent("feishu.upload_file", filePath=str(path))
            return f"dry-run-file-token:{path.name}"
        self._assert_bitable_configured()
        content = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parent_types = (
            ["bitable_image", "bitable_file"]
            if content_type.startswith("image/")
            else ["bitable_file"]
        )
        last_error: Exception | None = None
        assert self.config is not None
        for parent_type in parent_types:
            try:
                data = await self._request(
                    "POST",
                    "/drive/v1/medias/upload_all",
                    data={
                        "file_name": path.name,
                        "parent_type": parent_type,
                        "parent_node": self.config.bitable_app_token,
                        "size": str(len(content)),
                        "extra": (
                            '{"drive_route_token":"'
                            f'{self.config.bitable_app_token}"'
                            "}"
                        ),
                    },
                    files={"file": (path.name, content, content_type)},
                )
                token = str(
                    data.get("data", {}).get("file_token")
                    or data.get("data", {}).get("fileToken")
                    or data.get("data", {}).get("token")
                    or ""
                )
                if not token:
                    raise ValueError("missing_feishu_file_token")
                return token
            except Exception as exc:
                last_error = exc
        raise last_error or ValueError("upload_feishu_bitable_attachment_failed")

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        assert self.token_provider is not None
        headers = {"Authorization": f"Bearer {await self.token_provider.tenant_access_token()}"}
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30,
            headers=headers,
            transport=self.transport,
        ) as client:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
        data = response.json()
        if int(data.get("code") or 0) != 0:
            raise ValueError(str(data.get("msg") or "feishu_bitable_request_failed"))
        return data

    def _table_url(self, table_id: str) -> str:
        assert self.config is not None
        return f"/bitable/v1/apps/{self.config.bitable_app_token}/tables/{table_id}"

    def _assert_bitable_configured(self) -> None:
        assert self.config is not None
        if not self.config.bitable_app_token:
            raise ValueError("missing_feishu_bitable_app_token")


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
