from __future__ import annotations

import json
import sys

DENIED_LOCAL_TOOLS = frozenset({"Bash", "apply_patch", "Edit", "Write"})
ALLOWED_MCP_TOOLS = frozenset(
    {
        "mcp__codegraph__codegraph_explore",
        "mcp__codegraph__codegraph_node",
        "mcp__recruit_ops__recruitment_preflight",
        "mcp__recruit_ops__processing_start",
        "mcp__recruit_ops__processing_pause",
        "mcp__recruit_ops__processing_status",
        "mcp__recruit_ops__data_health",
        "mcp__recruit_ops__daily_report",
    }
)


def denial(reason: str) -> dict[str, object]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def evaluate_event(event: object) -> dict[str, object] | None:
    if not isinstance(event, dict):
        return denial("Hook event must be a JSON object.")
    if event.get("hook_event_name") != "PreToolUse":
        return denial("Expected a PreToolUse hook event.")

    tool_name = event.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        return denial("tool_name must be a non-empty string.")
    if tool_name in DENIED_LOCAL_TOOLS:
        return denial("Tool is denied by managed policy.")
    if tool_name.startswith("mcp__") and tool_name not in ALLOWED_MCP_TOOLS:
        return denial("MCP tool is not allowlisted.")
    return None


def decision_for_raw_event(raw_event: str) -> dict[str, object] | None:
    try:
        event = json.loads(raw_event)
    except json.JSONDecodeError:
        return denial("Invalid JSON hook event.")
    return evaluate_event(event)


def configure_standard_streams() -> None:
    for stream, errors in ((sys.stdin, "strict"), (sys.stdout, "backslashreplace")):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors=errors)
        except (OSError, TypeError, ValueError):
            continue


def main() -> int:
    configure_standard_streams()
    try:
        raw_event = sys.stdin.read()
    except UnicodeError:
        result = denial("Invalid UTF-8 hook event.")
    else:
        result = decision_for_raw_event(raw_event)

    if result is not None:
        json.dump(result, sys.stdout, ensure_ascii=True, separators=(",", ":"))
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
