from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "codex_server_policy_hook.py"

ALLOWED_MCP_TOOLS = (
    "mcp__codegraph__codegraph_explore",
    "mcp__codegraph__codegraph_node",
    "mcp__recruit_ops__recruitment_preflight",
    "mcp__recruit_ops__processing_start",
    "mcp__recruit_ops__processing_pause",
    "mcp__recruit_ops__processing_status",
    "mcp__recruit_ops__data_health",
    "mcp__recruit_ops__daily_report",
)


def _run_hook(raw_event: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        input=raw_event,
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=REPO_ROOT,
        check=False,
    )


def _event(tool_name: object, **extra: object) -> str:
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        **extra,
    }
    return json.dumps(event)


def _assert_denied(
    completed: subprocess.CompletedProcess[str],
    expected_reason: str,
) -> None:
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    output = json.loads(completed.stdout)
    assert output == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": expected_reason,
        }
    }


@pytest.mark.parametrize(
    "tool_name",
    (
        "Bash",
        "shell",
        "Shell",
        "exec_command",
        "unified_exec",
        "apply_patch",
        "Edit",
        "Write",
    ),
)
def test_denies_managed_local_mutation_tools(tool_name: str) -> None:
    completed = _run_hook(_event(tool_name))

    _assert_denied(completed, "Tool is denied by managed policy.")


@pytest.mark.parametrize("tool_name", ALLOWED_MCP_TOOLS)
def test_exact_allowlisted_mcp_tools_continue_silently(tool_name: str) -> None:
    completed = _run_hook(_event(tool_name))

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""


@pytest.mark.parametrize(
    "tool_name",
    (
        "mcp__codegraph__codegraph_search",
        "mcp__codegraph__codegraph_explore_extra",
        "mcp__codegraph__Codegraph_explore",
        "mcp__recruit_ops__processing_start_extra",
        "mcp__other__daily_report",
    ),
)
def test_denies_every_other_mcp_tool(tool_name: str) -> None:
    completed = _run_hook(_event(tool_name))

    _assert_denied(completed, "MCP tool is not allowlisted.")


@pytest.mark.parametrize("tool_name", ("update_plan", "request_user_input", "view_image"))
def test_other_local_function_tools_continue_silently(tool_name: str) -> None:
    completed = _run_hook(_event(tool_name))

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""


@pytest.mark.parametrize(
    ("raw_event", "expected_reason"),
    (
        ("{", "Invalid JSON hook event."),
        (json.dumps(None), "Hook event must be a JSON object."),
        (json.dumps([]), "Hook event must be a JSON object."),
        (json.dumps("event"), "Hook event must be a JSON object."),
        (
            json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Bash"}),
            "Expected a PreToolUse hook event.",
        ),
        (json.dumps({"tool_name": "Bash"}), "Expected a PreToolUse hook event."),
        (
            json.dumps({"hook_event_name": "PreToolUse"}),
            "tool_name must be a non-empty string.",
        ),
        (_event(None), "tool_name must be a non-empty string."),
        (_event(7), "tool_name must be a non-empty string."),
        (_event(""), "tool_name must be a non-empty string."),
        (_event("   "), "tool_name must be a non-empty string."),
    ),
)
def test_invalid_hook_inputs_fail_closed(raw_event: str, expected_reason: str) -> None:
    completed = _run_hook(raw_event)

    _assert_denied(completed, expected_reason)


def test_denial_never_echoes_tool_input_or_secrets() -> None:
    secret = "server-token-super-secret"
    completed = _run_hook(
        _event(
            "Bash",
            tool_input={"command": "deploy", "authorization": secret},
        )
    )

    _assert_denied(completed, "Tool is denied by managed policy.")
    assert secret not in completed.stdout
    assert secret not in completed.stderr
