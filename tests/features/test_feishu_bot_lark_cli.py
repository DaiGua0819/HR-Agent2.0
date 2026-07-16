from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from app.features.feishu_bot.lark_cli import (
    LarkCliError,
    LarkCommandResult,
    LarkEventSource,
    LarkReplyClient,
    _resolve_lark_cli_prefix,
)


class _LineStream:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode("utf-8") for line in lines]

    async def readline(self) -> bytes:
        await asyncio.sleep(0)
        if not self._lines:
            return b""
        return self._lines.pop(0)


class _Stdin:
    def __init__(self) -> None:
        self.closed = False
        self.waited = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        self.waited = True


class _Process:
    def __init__(self, *, stdout: list[str], stderr: list[str], returncode: int = 0) -> None:
        self.stdout = _LineStream(stdout)
        self.stderr = _LineStream(stderr)
        self.stdin = _Stdin()
        self.returncode: int | None = None
        self._final_returncode = returncode
        self.terminated = False
        self.killed = False

    async def wait(self) -> int:
        self.returncode = self._final_returncode
        return self._final_returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = self._final_returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = self._final_returncode


def _event_payload() -> dict[str, str]:
    return {
        "event_id": "evt-1",
        "message_id": "om-1",
        "sender_id": "ou-member",
        "chat_id": "oc-p2p",
        "chat_type": "p2p",
        "message_type": "text",
        "content": "昨天处理了多少人？",
        "create_time": "1784179200000",
    }


def test_event_source_waits_for_ready_and_parses_ndjson(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    process = _Process(
        stderr=[
            "starting event client\n",
            "[event] ready event_key=im.message.receive_v1\n",
        ],
        stdout=[json.dumps(_event_payload(), ensure_ascii=False) + "\n"],
    )

    async def process_factory(*argv: str, **kwargs: object) -> _Process:
        calls.append({"argv": list(argv), "kwargs": kwargs})
        return process

    async def scenario() -> None:
        source = LarkEventSource(
            profile="hr-agent-readonly-bot",
            cwd=tmp_path,
            process_factory=process_factory,
        )
        events = source.events()
        event = await anext(events)

        assert event.event_id == "evt-1"
        assert event.message_id == "om-1"
        assert event.sender_open_id == "ou-member"
        assert event.content == "昨天处理了多少人？"

        await source.close()
        await events.aclose()

    asyncio.run(scenario())

    assert len(calls) == 1
    argv = calls[0]["argv"]
    assert isinstance(argv, list)
    assert argv[-7:] == [
        "--profile",
        "hr-agent-readonly-bot",
        "event",
        "consume",
        "im.message.receive_v1",
        "--as",
        "bot",
    ]
    assert calls[0]["kwargs"]["shell"] is False
    assert process.stdin.closed is True
    assert process.stdin.waited is True
    assert process.terminated is False
    assert process.killed is False


def test_event_source_surfaces_structured_startup_failure(tmp_path: Path) -> None:
    envelope = {
        "ok": False,
        "error": {
            "type": "permission",
            "subtype": "missing_scope",
            "message": "missing required scope",
            "missing_scopes": ["im:message.p2p_msg:readonly"],
        },
    }
    process = _Process(
        stderr=[json.dumps(envelope) + "\n"],
        stdout=[],
        returncode=3,
    )

    async def process_factory(*_argv: str, **_kwargs: object) -> _Process:
        return process

    async def scenario() -> None:
        source = LarkEventSource(
            profile="hr-agent-readonly-bot",
            cwd=tmp_path,
            process_factory=process_factory,
        )
        with pytest.raises(LarkCliError) as error:
            await anext(source.events())
        assert error.value.error_type == "permission"
        assert error.value.subtype == "missing_scope"
        assert error.value.details["missing_scopes"] == [
            "im:message.p2p_msg:readonly"
        ]

    asyncio.run(scenario())


def test_reply_client_uses_named_profile_bot_identity_and_idempotency(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    async def runner(
        argv: list[str],
        *,
        cwd: Path,
        timeout_seconds: float,
    ) -> LarkCommandResult:
        calls.append(
            {
                "argv": argv,
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
            }
        )
        return LarkCommandResult(
            returncode=0,
            stdout=json.dumps({"data": {"message_id": "om-reply"}}),
            stderr="",
        )

    client = LarkReplyClient(
        profile="hr-agent-readonly-bot",
        cwd=tmp_path,
        runner=runner,
    )
    response_message_id = asyncio.run(
        client.reply(
            "om-source",
            "昨日共处理 3 人。",
            idempotency_key="feishu-bot:evt-1",
        )
    )

    assert response_message_id == "om-reply"
    assert calls == [
        {
            "argv": [
                "lark-cli",
                "--profile",
                "hr-agent-readonly-bot",
                "im",
                "+messages-reply",
                "--as",
                "bot",
                "--message-id",
                "om-source",
                "--text",
                "昨日共处理 3 人。",
                "--idempotency-key",
                "feishu-bot:evt-1",
                "--json",
            ],
            "cwd": tmp_path,
            "timeout_seconds": 30.0,
        }
    ]


def test_reply_client_raises_structured_cli_error(tmp_path: Path) -> None:
    async def runner(
        _argv: list[str],
        *,
        cwd: Path,
        timeout_seconds: float,
    ) -> LarkCommandResult:
        del cwd, timeout_seconds
        return LarkCommandResult(
            returncode=3,
            stdout="",
            stderr=json.dumps(
                {
                    "ok": False,
                    "error": {
                        "type": "auth",
                        "subtype": "missing_token",
                        "message": "bot token unavailable",
                    },
                }
            ),
        )

    client = LarkReplyClient(
        profile="hr-agent-readonly-bot",
        cwd=tmp_path,
        runner=runner,
    )

    with pytest.raises(LarkCliError, match="bot token unavailable") as error:
        asyncio.run(
            client.reply(
                "om-source",
                "测试",
                idempotency_key="feishu-bot:evt-1",
            )
        )
    assert error.value.error_type == "auth"
    assert error.value.subtype == "missing_token"


def test_windows_lark_cli_resolution_avoids_cmd_shell(tmp_path: Path) -> None:
    node = tmp_path / "node.exe"
    command = tmp_path / "lark-cli.cmd"
    script = tmp_path / "node_modules" / "@larksuite" / "cli" / "scripts" / "run.js"
    node.touch()
    command.touch()
    script.parent.mkdir(parents=True)
    script.touch()

    resolved = _resolve_lark_cli_prefix(
        "lark-cli",
        platform_name="nt",
        which=lambda name: str(command) if name == "lark-cli.cmd" else None,
    )

    assert resolved == [str(node), str(script)]
