"""Narrow newline-delimited JSON-RPC MCP server for recruitment operations."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol, TextIO

from app.features.feishu_bot.runtime_control import (
    AgentManagerBatchResult,
    summarize_manager_events,
)

MCP_PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "recruit-ops-mcp"
SERVER_VERSION = "1.0.0"

_REPORT_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_EMPTY_INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
_READ_ONLY_ANNOTATIONS: dict[str, object] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

TOOL_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "name": "recruitment_preflight",
        "description": "Run the fixed recruitment runtime preflight checks.",
        "inputSchema": _EMPTY_INPUT_SCHEMA,
        "outputSchema": {"type": "object"},
        "annotations": _READ_ONLY_ANNOTATIONS,
    },
    {
        "name": "processing_start",
        "description": "Adopt the configured runtime and run one guarded processing batch.",
        "inputSchema": _EMPTY_INPUT_SCHEMA,
        "outputSchema": {"type": "object"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    },
    {
        "name": "processing_pause",
        "description": "Request the fixed graceful recruitment processing pause.",
        "inputSchema": _EMPTY_INPUT_SCHEMA,
        "outputSchema": {"type": "object"},
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    },
    {
        "name": "processing_status",
        "description": "Read the parsed recruitment processing status.",
        "inputSchema": _EMPTY_INPUT_SCHEMA,
        "outputSchema": {"type": "object"},
        "annotations": _READ_ONLY_ANNOTATIONS,
    },
    {
        "name": "data_health",
        "description": "Read local recruitment data and synchronization health.",
        "inputSchema": _EMPTY_INPUT_SCHEMA,
        "outputSchema": {"type": "object"},
        "annotations": _READ_ONLY_ANNOTATIONS,
    },
    {
        "name": "daily_report",
        "description": "Read the recruitment report for one Asia/Shanghai calendar date.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "pattern": r"^\d{4}-\d{2}-\d{2}$",
                }
            },
            "required": ["date"],
            "additionalProperties": False,
        },
        "outputSchema": {"type": "object"},
        "annotations": _READ_ONLY_ANNOTATIONS,
    },
)

_TOOL_NAMES = frozenset(tool["name"] for tool in TOOL_DEFINITIONS)
_NO_ARGUMENT_TOOLS = _TOOL_NAMES - {"daily_report"}


class RecruitmentOpsManager(Protocol):
    async def preflight(self) -> dict[str, object]: ...

    async def start_runtime(self) -> None: ...

    async def run_batch(self) -> AgentManagerBatchResult: ...

    async def request_stop(self, reason: str) -> None: ...

    async def status(self) -> dict[str, object]: ...

    async def data_health(self) -> dict[str, object]: ...

    async def daily_report(self, date_text: str) -> dict[str, object]: ...


@dataclass(frozen=True)
class ToolExecution:
    payload: dict[str, object]
    is_error: bool = False


class RecruitmentOpsService:
    """Map the six public tools to fixed manager operations."""

    def __init__(self, manager: RecruitmentOpsManager) -> None:
        self.manager = manager

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object],
    ) -> ToolExecution:
        _validate_tool_arguments(name, arguments)
        if name == "recruitment_preflight":
            payload = await self.manager.preflight()
            return ToolExecution(payload, is_error=payload.get("ok") is False)
        if name == "processing_start":
            await self.manager.start_runtime()
            batch = await self.manager.run_batch()
            payload = _completion_summary(batch)
            return ToolExecution(payload, is_error=payload["ok"] is False)
        if name == "processing_pause":
            await self.manager.request_stop("feishu_admin_pause")
            return ToolExecution({"ok": True, "status": "pause_requested"})
        if name == "processing_status":
            return ToolExecution(await self.manager.status())
        if name == "data_health":
            return ToolExecution(await self.manager.data_health())
        if name == "daily_report":
            return ToolExecution(await self.manager.daily_report(str(arguments["date"])))
        raise UnknownToolError(name)


class InvalidToolArguments(ValueError):
    pass


class UnknownToolError(ValueError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Unknown tool: {name}")


class RecruitmentOpsMcpServer:
    """Handle one JSON-RPC request per input line without external MCP libraries."""

    def __init__(self, service: RecruitmentOpsService) -> None:
        self.service = service

    async def handle(self, message: object) -> dict[str, object] | None:
        if not isinstance(message, dict):
            return _error_response(None, -32600, "Invalid Request")

        has_id = "id" in message
        request_id = message.get("id") if has_id else None
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return _error_response(request_id, -32600, "Invalid Request")
        if not has_id:
            return None

        method = message["method"]
        params = message.get("params", {})
        if method == "initialize":
            if not isinstance(params, dict):
                return _error_response(request_id, -32602, "Invalid params")
            return _success_response(
                request_id,
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            )
        if method == "ping":
            if not _empty_params(params):
                return _error_response(request_id, -32602, "Invalid params")
            return _success_response(request_id, {})
        if method == "tools/list":
            if not _empty_params(params):
                return _error_response(request_id, -32602, "Invalid params")
            return _success_response(request_id, {"tools": deepcopy(TOOL_DEFINITIONS)})
        if method == "tools/call":
            return await self._handle_tool_call(request_id, params)
        return _error_response(request_id, -32601, "Method not found")

    async def handle_line(self, line: str) -> str | None:
        if not line.strip():
            return None
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response = _error_response(None, -32700, "Parse error")
        else:
            response = await self.handle(message)
        if response is None:
            return None
        return _json_text(response)

    async def serve(self, *, input_stream: TextIO, output_stream: TextIO) -> None:
        for line in input_stream:
            response = await self.handle_line(line)
            if response is None:
                continue
            output_stream.write(response)
            output_stream.write("\n")
            output_stream.flush()

    async def _handle_tool_call(
        self,
        request_id: object,
        params: object,
    ) -> dict[str, object]:
        if not isinstance(params, dict) or not set(params) <= {"name", "arguments"}:
            return _error_response(request_id, -32602, "Invalid params")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error_response(request_id, -32602, "Invalid params")
        if name not in _TOOL_NAMES:
            return _error_response(request_id, -32602, f"Unknown tool: {name}")
        try:
            execution = await self.service.call_tool(name, arguments)
        except InvalidToolArguments:
            return _error_response(request_id, -32602, "Invalid params")
        except Exception as exc:
            execution = ToolExecution(
                {"ok": False, "error": _public_error(exc)},
                is_error=True,
            )
        return _success_response(
            request_id,
            _tool_result(execution.payload, is_error=execution.is_error),
        )


def _validate_tool_arguments(name: str, arguments: Mapping[str, object]) -> None:
    if name in _NO_ARGUMENT_TOOLS:
        if arguments:
            raise InvalidToolArguments("tool_accepts_no_arguments")
        return
    if name == "daily_report":
        if set(arguments) != {"date"}:
            raise InvalidToolArguments("daily_report_date_required")
        date_text = arguments["date"]
        if not isinstance(date_text, str) or _REPORT_DATE_PATTERN.fullmatch(date_text) is None:
            raise InvalidToolArguments("daily_report_date_invalid")
        return
    raise UnknownToolError(name)


def _completion_summary(batch: AgentManagerBatchResult) -> dict[str, object]:
    summary = summarize_manager_events(batch.events)
    return {
        "ok": batch.status in {"complete", "paused", "stop_requested"},
        "runId": batch.run_id,
        "status": batch.status,
        "processedContacts": summary.processed_contacts,
        "businessResumeAcquisitions": summary.business_resume_acquisitions,
        "resumeRequestsWaiting": summary.resume_requests_waiting,
        "anomalies": summary.anomalies,
        "anomalyReasons": list(summary.anomaly_reasons),
        "byPlatform": {
            platform: {
                "processedContacts": item.processed_contacts,
                "businessResumeAcquisitions": item.business_resume_acquisitions,
                "resumeRequestsWaiting": item.resume_requests_waiting,
                "anomalies": item.anomalies,
            }
            for platform, item in summary.by_platform.items()
        },
    }


def _tool_result(payload: dict[str, object], *, is_error: bool) -> dict[str, object]:
    return {
        "content": [{"type": "text", "text": _json_text(payload)}],
        "structuredContent": payload,
        "isError": is_error,
    }


def _success_response(request_id: object, result: object) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(
    request_id: object,
    code: int,
    message: str,
) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _empty_params(value: object) -> bool:
    return isinstance(value, dict) and not value


def _public_error(error: Exception) -> str:
    message = " ".join(str(error).split())
    return (message or type(error).__name__)[:800]


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
