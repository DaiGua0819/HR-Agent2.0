from __future__ import annotations

import asyncio
import importlib
import io
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest
from app.features.feishu_bot.runtime_control import AgentManagerBatchResult


def _mcp_module() -> ModuleType:
    return importlib.import_module("app.features.recruit_ops_mcp.server")


def _script_module() -> ModuleType:
    return importlib.import_module("scripts.run_recruit_ops_mcp")


class _FakeManager:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.preflight_result: dict[str, object] = {"ok": True, "warnings": []}
        self.status_result: dict[str, object] = {
            "currentRun": {"runId": "run-status", "status": "running"}
        }
        self.health_result: dict[str, object] = {"generatedAt": "2026-07-20T08:00:00Z"}
        self.report_result: dict[str, object] = {
            "date": "2026-07-20",
            "processedContacts": 5,
        }
        self.batch_result = AgentManagerBatchResult(
            run_id="run-complete",
            status="complete",
            events=(),
        )
        self.failures: dict[str, Exception] = {}

    def _raise_failure(self, name: str) -> None:
        failure = self.failures.get(name)
        if failure is not None:
            raise failure

    async def preflight(self) -> dict[str, object]:
        self.calls.append("preflight")
        self._raise_failure("preflight")
        return self.preflight_result

    async def start_runtime(self) -> None:
        self.calls.append("start_runtime")
        self._raise_failure("start_runtime")

    async def run_batch(self) -> AgentManagerBatchResult:
        self.calls.append("run_batch")
        self._raise_failure("run_batch")
        return self.batch_result

    async def request_stop(self, reason: str) -> None:
        self.calls.append(("request_stop", reason))
        self._raise_failure("request_stop")

    async def status(self) -> dict[str, object]:
        self.calls.append("status")
        self._raise_failure("status")
        return self.status_result

    async def data_health(self) -> dict[str, object]:
        self.calls.append("data_health")
        self._raise_failure("data_health")
        return self.health_result

    async def daily_report(self, date_text: str) -> dict[str, object]:
        self.calls.append(("daily_report", date_text))
        self._raise_failure("daily_report")
        return self.report_result


def _server(manager: _FakeManager):
    module = _mcp_module()
    return module.RecruitmentOpsMcpServer(module.RecruitmentOpsService(manager))


def _request(
    server,
    method: str,
    *,
    request_id: object = 1,
    params: dict[str, object] | None = None,
) -> dict[str, object] | None:
    message: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        message["params"] = params
    return asyncio.run(server.handle(message))


def _call_tool(
    server,
    name: str,
    arguments: dict[str, object] | None = None,
    *,
    request_id: object = 1,
) -> dict[str, object]:
    params: dict[str, object] = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    response = _request(
        server,
        "tools/call",
        request_id=request_id,
        params=params,
    )
    assert response is not None
    return response


def test_initialize_ping_and_notifications_follow_json_rpc() -> None:
    module = _mcp_module()
    manager = _FakeManager()
    server = _server(manager)

    initialized = _request(
        server,
        "initialize",
        params={
            "protocolVersion": module.MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1"},
        },
    )
    assert initialized == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "protocolVersion": module.MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "recruit-ops-mcp", "version": "1.0.0"},
        },
    }
    assert _request(server, "ping", request_id=2) == {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {},
    }

    initialized_notification = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
        )
    )
    tool_notification = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "processing_start", "arguments": {}},
            }
        )
    )
    assert initialized_notification is None
    assert tool_notification is None
    assert manager.calls == []


def test_tools_list_exposes_only_narrow_schemas_and_accurate_annotations() -> None:
    server = _server(_FakeManager())

    response = _request(server, "tools/list", params={})

    assert response is not None
    tools = response["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "recruitment_preflight",
        "processing_start",
        "processing_pause",
        "processing_status",
        "data_health",
        "daily_report",
    ]
    by_name = {tool["name"]: tool for tool in tools}
    empty_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    for name in {
        "recruitment_preflight",
        "processing_start",
        "processing_pause",
        "processing_status",
        "data_health",
    }:
        assert by_name[name]["inputSchema"] == empty_schema
    assert by_name["daily_report"]["inputSchema"] == {
        "type": "object",
        "properties": {
            "date": {
                "type": "string",
                "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
            }
        },
        "required": ["date"],
        "additionalProperties": False,
    }
    assert all(tool["outputSchema"] == {"type": "object"} for tool in tools)

    for name in {
        "recruitment_preflight",
        "processing_status",
        "data_health",
        "daily_report",
    }:
        assert by_name[name]["annotations"] == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    assert by_name["processing_start"]["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    }
    assert by_name["processing_pause"]["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }


def test_processing_start_runs_fixed_sequence_and_returns_sanitized_summary() -> None:
    manager = _FakeManager()
    manager.batch_result = AgentManagerBatchResult(
        run_id="run-42",
        status="complete",
        events=(
            {
                "event": "contact_result",
                "platform": "boss",
                "owner": "must-not-be-returned",
                "secret": "must-not-be-returned",
                "summary": {"processed": 1, "conversationId": "boss-1"},
                "response": {
                    "decision": {
                        "action": "request_resume",
                        "result": {"requested": True, "confirmed": True},
                    }
                },
                "classification": {"is_anomaly": False, "reasons": []},
            },
            {
                "event": "contact_result",
                "platform": "job51",
                "summary": {
                    "processed": 2,
                    "conversationId": "job51-1",
                    "resumeHandling": "local_resume_downloaded",
                },
                "response": {"path": "C:/sensitive/resume.pdf"},
                "classification": {"is_anomaly": False, "reasons": []},
            },
        ),
        skipped_targets=("owner:zhilian",),
    )
    server = _server(manager)

    response = _call_tool(server, "processing_start", {})

    assert manager.calls == ["start_runtime", "run_batch"]
    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"] == {
        "ok": True,
        "runId": "run-42",
        "status": "complete",
        "processedContacts": 3,
        "businessResumeAcquisitions": 2,
        "resumeRequestsWaiting": 0,
        "anomalies": 0,
        "anomalyReasons": [],
        "byPlatform": {
            "boss": {
                "processedContacts": 1,
                "businessResumeAcquisitions": 1,
                "resumeRequestsWaiting": 0,
                "anomalies": 0,
            },
            "job51": {
                "processedContacts": 2,
                "businessResumeAcquisitions": 1,
                "resumeRequestsWaiting": 0,
                "anomalies": 0,
            },
        },
    }
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    assert "must-not-be-returned" not in result["content"][0]["text"]
    assert "sensitive" not in result["content"][0]["text"]


def test_pause_and_read_only_tools_use_only_fixed_manager_operations() -> None:
    manager = _FakeManager()
    server = _server(manager)

    preflight = _call_tool(server, "recruitment_preflight")
    status = _call_tool(server, "processing_status")
    health = _call_tool(server, "data_health")
    report = _call_tool(server, "daily_report", {"date": "2026-07-20"})
    pause = _call_tool(server, "processing_pause", {})

    assert preflight["result"]["structuredContent"] == manager.preflight_result
    assert status["result"]["structuredContent"] == manager.status_result
    assert health["result"]["structuredContent"] == manager.health_result
    assert report["result"]["structuredContent"] == manager.report_result
    assert pause["result"]["structuredContent"] == {
        "ok": True,
        "status": "pause_requested",
    }
    assert manager.calls == [
        "preflight",
        "status",
        "data_health",
        ("daily_report", "2026-07-20"),
        ("request_stop", "feishu_admin_pause"),
    ]
    assert all(
        response["result"]["isError"] is False
        for response in (preflight, status, health, report, pause)
    )


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("recruitment_preflight", {"owner": "alice"}),
        ("processing_start", {"command": "whoami"}),
        ("processing_pause", {"reason": "custom"}),
        ("processing_status", {"platform": "boss"}),
        ("data_health", {"path": "C:/data"}),
        ("daily_report", {"date": "2026-07-20", "environment": "prod"}),
        ("daily_report", {"date": "2026-07-20 --timezone UTC"}),
        ("daily_report", {"date": "２０２６-０７-２０"}),
        ("daily_report", {"date": "2026-02-30"}),
    ],
)
def test_tool_calls_reject_all_non_schema_inputs(
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    manager = _FakeManager()
    server = _server(manager)

    response = _call_tool(server, tool_name, arguments)

    assert response["error"]["code"] == -32602
    assert manager.calls == []


def test_unknown_methods_and_tools_return_json_rpc_errors() -> None:
    server = _server(_FakeManager())

    unknown_method = _request(server, "recruitment/run", request_id=7)
    unknown_tool = _call_tool(server, "shell", {}, request_id=8)

    assert unknown_method == {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {"code": -32601, "message": "Method not found"},
    }
    assert unknown_tool == {
        "jsonrpc": "2.0",
        "id": 8,
        "error": {"code": -32602, "message": "Unknown tool: shell"},
    }


@pytest.mark.parametrize("request_id", (None, True, 1.25, {"nested": 1}))
def test_invalid_mcp_request_ids_fail_closed(request_id: object) -> None:
    server = _server(_FakeManager())

    response = _request(server, "ping", request_id=request_id)

    assert response == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32600, "message": "Invalid Request"},
    }


@pytest.mark.parametrize(
    "message",
    (
        {"jsonrpc": "1.0", "id": {"nested": 1}, "method": "ping"},
        {"jsonrpc": "2.0", "id": True, "method": 7},
    ),
)
def test_malformed_envelopes_never_echo_invalid_request_ids(
    message: dict[str, object],
) -> None:
    server = _server(_FakeManager())

    response = asyncio.run(server.handle(message))

    assert response == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32600, "message": "Invalid Request"},
    }


def test_initialize_requires_protocol_fields_and_allows_request_meta() -> None:
    server = _server(_FakeManager())

    invalid = _request(server, "initialize", params={})
    valid = _request(
        server,
        "initialize",
        request_id="init-1",
        params={
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "codex", "version": "0.130.0"},
            "_meta": {"traceId": "trace-1"},
        },
    )

    assert invalid == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32602, "message": "Invalid params"},
    }
    assert valid is not None
    assert valid["id"] == "init-1"
    assert valid["result"]["protocolVersion"] == "2025-06-18"


@pytest.mark.parametrize(
    "params",
    (
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {
                "name": "codex",
                "version": "0.130.0",
                "title": 123,
            },
        },
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {"roots": "yes"},
            "clientInfo": {"name": "codex", "version": "0.130.0"},
        },
    ),
)
def test_initialize_rejects_invalid_known_nested_fields(
    params: dict[str, object],
) -> None:
    server = _server(_FakeManager())

    response = _request(server, "initialize", params=params)

    assert response == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32602, "message": "Invalid params"},
    }


def test_ping_list_and_tool_call_accept_valid_request_meta() -> None:
    manager = _FakeManager()
    server = _server(manager)

    ping = _request(server, "ping", params={"_meta": {"progressToken": "ping"}})
    listed = _request(
        server,
        "tools/list",
        request_id=2,
        params={"_meta": {"progressToken": "list"}},
    )
    health = _request(
        server,
        "tools/call",
        request_id=3,
        params={
            "name": "data_health",
            "arguments": {},
            "_meta": {"progressToken": "health"},
        },
    )

    assert ping == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert listed is not None
    assert listed["id"] == 2
    assert health is not None
    assert health["id"] == 3
    assert manager.calls == ["data_health"]


def test_non_json_numbers_are_rejected_and_never_emitted() -> None:
    manager = _FakeManager()
    manager.health_result = {"ok": True, "score": float("nan")}
    server = _server(manager)

    parsed = asyncio.run(server.handle_line('{"jsonrpc":"2.0","id":NaN,"method":"ping"}'))
    response = _call_tool(server, "data_health")

    assert parsed is not None
    assert json.loads(parsed) == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": "Parse error"},
    }
    assert response["result"] == {
        "content": [
            {
                "type": "text",
                "text": '{"ok":false,"error":"tool_result_not_json"}',
            }
        ],
        "structuredContent": {"ok": False, "error": "tool_result_not_json"},
        "isError": True,
    }


def test_tool_failures_return_structured_content_text_and_is_error() -> None:
    manager = _FakeManager()
    manager.preflight_result = {
        "ok": False,
        "errors": [{"reason": "control_plane_not_ready"}],
    }
    server = _server(manager)

    preflight = _call_tool(server, "recruitment_preflight")
    assert preflight["result"]["isError"] is True
    assert (
        json.loads(preflight["result"]["content"][0]["text"])
        == preflight["result"]["structuredContent"]
    )

    manager.failures["status"] = RuntimeError("agent_manager_status_invalid_json")
    failed_status = _call_tool(server, "processing_status", request_id=2)
    assert failed_status["result"] == {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {"ok": False, "error": "agent_manager_status_invalid_json"},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }
        ],
        "structuredContent": {
            "ok": False,
            "error": "agent_manager_status_invalid_json",
        },
        "isError": True,
    }


def test_stdio_server_emits_one_json_response_per_request_line() -> None:
    server = _server(_FakeManager())
    input_stream = io.StringIO(
        "\n".join(
            [
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                        "params": {},
                    }
                ),
                "not-json",
            ]
        )
        + "\n"
    )
    output_stream = io.StringIO()

    asyncio.run(server.serve(input_stream=input_stream, output_stream=output_stream))

    lines = output_stream.getvalue().splitlines()
    assert len(lines) == 2
    responses = {response["id"]: response for response in map(json.loads, lines)}
    assert responses[1] == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert responses[None] == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": "Parse error"},
    }


def test_stdio_server_handles_pause_and_ping_while_start_is_running() -> None:
    class _BlockingManager(_FakeManager):
        def __init__(self) -> None:
            super().__init__()
            self.release = asyncio.Event()

        async def run_batch(self) -> AgentManagerBatchResult:
            self.calls.append("run_batch")
            await self.release.wait()
            return self.batch_result

        async def request_stop(self, reason: str) -> None:
            self.calls.append(("request_stop", reason))
            self.release.set()

    manager = _BlockingManager()
    server = _server(manager)
    input_stream = io.StringIO(
        "\n".join(
            json.dumps(message)
            for message in (
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "processing_start", "arguments": {}},
                },
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "processing_pause", "arguments": {}},
                },
            )
        )
        + "\n"
    )
    output_stream = io.StringIO()

    asyncio.run(
        asyncio.wait_for(
            server.serve(input_stream=input_stream, output_stream=output_stream),
            timeout=1,
        )
    )

    responses = {
        response["id"]: response
        for response in map(json.loads, output_stream.getvalue().splitlines())
    }
    assert responses[2] == {"jsonrpc": "2.0", "id": 2, "result": {}}
    assert responses[3]["result"]["structuredContent"] == {
        "ok": True,
        "status": "pause_requested",
    }
    assert responses[1]["result"]["structuredContent"]["status"] == "complete"
    assert ("request_stop", "feishu_admin_pause") in manager.calls


def test_pause_during_runtime_start_prevents_batch_launch() -> None:
    class _StartupBlockingManager(_FakeManager):
        def __init__(self) -> None:
            super().__init__()
            self.start_entered = asyncio.Event()
            self.release_start = asyncio.Event()

        async def start_runtime(self) -> None:
            self.calls.append("start_runtime")
            self.start_entered.set()
            await self.release_start.wait()

        async def request_stop(self, reason: str) -> None:
            self.calls.append(("request_stop", reason))
            self.release_start.set()

    async def scenario() -> tuple[object, object, list[object]]:
        manager = _StartupBlockingManager()
        service = _mcp_module().RecruitmentOpsService(manager)
        start_task = asyncio.create_task(service.call_tool("processing_start", {}))
        await manager.start_entered.wait()
        pause_result = await service.call_tool("processing_pause", {})
        start_result = await asyncio.wait_for(start_task, timeout=1)
        return start_result, pause_result, manager.calls

    start_result, pause_result, calls = asyncio.run(scenario())

    assert start_result.payload == {
        "ok": True,
        "status": "pause_requested_before_batch",
        "processedContacts": 0,
        "businessResumeAcquisitions": 0,
        "resumeRequestsWaiting": 0,
        "anomalies": 0,
        "anomalyReasons": [],
        "byPlatform": {},
    }
    assert pause_result.payload == {"ok": True, "status": "pause_requested"}
    assert "run_batch" not in calls


def test_second_processing_start_is_rejected_while_batch_is_active() -> None:
    class _ActiveBatchManager(_FakeManager):
        def __init__(self) -> None:
            super().__init__()
            self.run_entered = asyncio.Event()
            self.release = asyncio.Event()

        async def run_batch(self) -> AgentManagerBatchResult:
            self.calls.append("run_batch")
            self.run_entered.set()
            await self.release.wait()
            return self.batch_result

    async def scenario() -> tuple[object, object, list[object]]:
        manager = _ActiveBatchManager()
        service = _mcp_module().RecruitmentOpsService(manager)
        first_task = asyncio.create_task(service.call_tool("processing_start", {}))
        await manager.run_entered.wait()
        second_result = await asyncio.wait_for(
            service.call_tool("processing_start", {}),
            timeout=0.2,
        )
        manager.release.set()
        first_result = await first_task
        return first_result, second_result, manager.calls

    first_result, second_result, calls = asyncio.run(scenario())

    assert first_result.is_error is False
    assert second_result == _mcp_module().ToolExecution(
        {"ok": False, "error": "processing_already_running"},
        is_error=True,
    )
    assert calls.count("start_runtime") == 1
    assert calls.count("run_batch") == 1


def test_launcher_accepts_only_validated_launch_configuration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _script_module()
    topology = tmp_path / "topology.json"
    topology.write_text("{}", encoding="utf-8")
    parser = module.build_parser()

    args = parser.parse_args(
        [
            "--topology",
            str(topology),
            "--max-contacts",
            "12",
            "--max-anomalies",
            "3",
            "--sleep",
            "0.25",
        ]
    )
    assert args.topology == topology.resolve()
    assert args.max_contacts == 12
    assert args.max_anomalies == 3
    assert args.sleep == 0.25

    invalid_arguments = [
        ["--topology", str(tmp_path / "missing.json")],
        ["--topology", str(topology), "--max-contacts", "-1"],
        ["--topology", str(topology), "--max-anomalies", "-1"],
        ["--topology", str(topology), "--sleep", "nan"],
        ["--topology", str(topology), "--owner", "alice"],
    ]
    for argv in invalid_arguments:
        with pytest.raises(SystemExit):
            parser.parse_args(argv)
    assert capsys.readouterr().out == ""


def test_launcher_forces_real_stdio_pipes_to_utf8(tmp_path: Path) -> None:
    topology = tmp_path / "topology.json"
    topology.write_text("{}", encoding="utf-8")
    wrapper = textwrap.dedent(
        """
        import os
        import scripts.run_recruit_ops_mcp as launcher
        from app.features.recruit_ops_mcp.server import RecruitmentOpsService

        class Manager:
            async def data_health(self):
                return {"状态": "正常"}

        launcher.build_service = lambda args: RecruitmentOpsService(Manager())
        raise SystemExit(launcher.main(["--topology", os.environ["TEST_TOPOLOGY"]]))
        """
    )
    request = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "data_health", "arguments": {}},
            }
        )
        + "\n"
    ).encode("utf-8")
    environment = {
        **os.environ,
        "PYTHONIOENCODING": "cp936",
        "PYTHONUTF8": "0",
        "TEST_TOPOLOGY": str(topology),
    }

    completed = subprocess.run(
        [sys.executable, "-c", wrapper],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        input=request,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    response = json.loads(completed.stdout.decode("utf-8"))
    assert response["result"]["structuredContent"] == {"状态": "正常"}


def test_launcher_constructs_sanitized_client_and_serves_json_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _script_module()
    topology = tmp_path / "topology.json"
    topology.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    class _Client:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(module, "AgentManagerSubprocessClient", _Client)
    args = module.build_parser().parse_args(
        [
            "--topology",
            str(topology),
            "--max-contacts",
            "8",
            "--max-anomalies",
            "2",
            "--sleep",
            "0.5",
        ]
    )

    service = module.build_service(args)

    assert isinstance(service.manager, _Client)
    assert captured["python_executable"] == sys.executable
    assert captured["manager_script"] == module.PROJECT_ROOT / "scripts" / "agent_manager.py"
    assert captured["topology_path"] == topology.resolve()
    assert captured["project_root"] == module.PROJECT_ROOT
    assert captured["max_contacts"] == 8
    assert captured["max_anomalies"] == 2
    assert captured["sleep_seconds"] == 0.5
    assert "skip_targets" not in captured
    assert {"OPENAI_API_KEY", "CODEX_API_KEY"} <= set(captured["blocked_env_names"])

    input_stream = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}) + "\n")
    output_stream = io.StringIO()
    exit_code = module.main(
        ["--topology", str(topology)],
        input_stream=input_stream,
        output_stream=output_stream,
    )

    assert exit_code == 0
    assert json.loads(output_stream.getvalue()) == {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {},
    }
    assert capsys.readouterr().out == ""
