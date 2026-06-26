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
from app.features.interview_center.feishu.client import FeishuAuthClient, FeishuTokenProvider
from app.settings import FeishuConfig, load_settings


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
