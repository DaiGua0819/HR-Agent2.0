"""Async adapters for the dedicated Feishu bot lark-cli profile."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.features.feishu_bot.models import BotEvent

ProcessFactory = Callable[..., Awaitable[Any]]
CommandRunner = Callable[..., Awaitable["LarkCommandResult"]]

_READY_MARKER = "[event] ready event_key=im.message.receive_v1"
_LARK_PARENT_ENV_ALLOW = {
    "ALL_PROXY",
    "ALLUSERSPROFILE",
    "APPDATA",
    "COLORTERM",
    "COMSPEC",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "LOCALAPPDATA",
    "NO_COLOR",
    "NO_PROXY",
    "OS",
    "PATH",
    "PATHEXT",
    "PROCESSOR_ARCHITECTURE",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMW6432",
    "SHELL",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "TZ",
    "USERPROFILE",
    "WINDIR",
}


@dataclass(frozen=True)
class LarkCommandResult:
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float = 0.0


class LarkCliError(RuntimeError):
    """Structured lark-cli process or protocol failure."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "lark_cli",
        subtype: str = "command_failed",
        details: dict[str, object] | None = None,
        returncode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.subtype = subtype
        self.details = dict(details or {})
        self.returncode = returncode


class LarkEventSource:
    """Consume normalized Feishu message events from one dedicated profile."""

    def __init__(
        self,
        *,
        profile: str,
        cwd: str | Path,
        command: str = "lark-cli",
        ready_timeout_seconds: float = 30.0,
        shutdown_timeout_seconds: float = 5.0,
        process_factory: ProcessFactory | None = None,
    ) -> None:
        self.profile = _required_text(profile, "feishu_bot_lark_profile_required")
        self.cwd = Path(cwd)
        self.command = command
        self.ready_timeout_seconds = max(1.0, float(ready_timeout_seconds))
        self.shutdown_timeout_seconds = max(1.0, float(shutdown_timeout_seconds))
        self.process_factory = process_factory or _create_subprocess_exec
        self._process: Any | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_lines: list[str] = []
        self._close_lock = asyncio.Lock()

    async def events(self) -> AsyncIterator[BotEvent]:
        if self._process is not None:
            raise RuntimeError("feishu_bot_event_source_already_started")
        self.cwd.mkdir(parents=True, exist_ok=True)
        argv = [
            *_resolve_lark_cli_prefix(self.command),
            "--profile",
            self.profile,
            "event",
            "consume",
            "im.message.receive_v1",
            "--as",
            "bot",
        ]
        self._process = await self.process_factory(
            *argv,
            cwd=str(self.cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_lark_parent_environment(os.environ),
            shell=False,
        )
        try:
            await asyncio.wait_for(
                self._wait_until_ready(),
                timeout=self.ready_timeout_seconds,
            )
            self._stderr_task = asyncio.create_task(self._drain_stderr())
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    returncode = await self._process.wait()
                    if returncode:
                        raise _error_from_text(
                            "\n".join(self._stderr_lines),
                            returncode=returncode,
                        )
                    return
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise LarkCliError(
                        "invalid lark-cli event NDJSON",
                        subtype="invalid_event_json",
                        details={"line": text[:500]},
                    ) from exc
                if not isinstance(payload, dict):
                    raise LarkCliError(
                        "invalid lark-cli event payload",
                        subtype="invalid_event_payload",
                    )
                event = BotEvent.from_payload(payload)
                event.validate_required()
                yield event
        except TimeoutError as exc:
            raise LarkCliError(
                "lark-cli event source did not become ready",
                subtype="ready_timeout",
            ) from exc
        finally:
            await self.close()

    async def close(self) -> None:
        async with self._close_lock:
            process = self._process
            if process is None:
                return
            stdin = getattr(process, "stdin", None)
            if stdin is not None and not getattr(stdin, "is_closing", lambda: False)():
                stdin.close()
                wait_closed = getattr(stdin, "wait_closed", None)
                if wait_closed is not None:
                    await wait_closed()
            if getattr(process, "returncode", None) is None:
                try:
                    await asyncio.wait_for(
                        process.wait(),
                        timeout=self.shutdown_timeout_seconds,
                    )
                except TimeoutError:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except TimeoutError:
                        process.kill()
                        await process.wait()
            stderr_task = self._stderr_task
            if stderr_task is not None and not stderr_task.done():
                stderr_task.cancel()
                try:
                    await stderr_task
                except asyncio.CancelledError:
                    pass
            self._stderr_task = None

    async def _wait_until_ready(self) -> None:
        while True:
            line = await self._process.stderr.readline()
            if not line:
                returncode = await self._process.wait()
                raise _error_from_text(
                    "\n".join(self._stderr_lines),
                    returncode=returncode,
                    default_message="lark-cli event source exited before ready",
                    default_subtype="startup_failed",
                )
            text = line.decode("utf-8", errors="replace").strip()
            self._remember_stderr(text)
            if _READY_MARKER in text:
                return
            envelope = _error_envelope(text)
            if envelope is not None:
                raise _error_from_envelope(envelope)

    async def _drain_stderr(self) -> None:
        while True:
            line = await self._process.stderr.readline()
            if not line:
                return
            self._remember_stderr(line.decode("utf-8", errors="replace").strip())

    def _remember_stderr(self, line: str) -> None:
        if not line:
            return
        self._stderr_lines.append(line[:2000])
        if len(self._stderr_lines) > 100:
            del self._stderr_lines[:-100]


class LarkReplyClient:
    """Reply to a Feishu message as the dedicated bot identity."""

    def __init__(
        self,
        *,
        profile: str,
        cwd: str | Path,
        command: str = "lark-cli",
        timeout_seconds: float = 30.0,
        runner: CommandRunner | None = None,
    ) -> None:
        self.profile = _required_text(profile, "feishu_bot_lark_profile_required")
        self.cwd = Path(cwd)
        self.command = command
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.runner = runner or _run_lark_command

    async def reply(
        self,
        message_id: str,
        text: str,
        *,
        idempotency_key: str,
    ) -> str:
        source_message_id = _required_text(
            message_id,
            "feishu_bot_reply_message_id_required",
        )
        response_text = _required_text(text, "feishu_bot_reply_text_required")
        stable_key = _required_text(
            idempotency_key,
            "feishu_bot_reply_idempotency_key_required",
        )
        argv = [
            self.command,
            "--profile",
            self.profile,
            "im",
            "+messages-reply",
            "--as",
            "bot",
            "--message-id",
            source_message_id,
            "--text",
            response_text,
            "--idempotency-key",
            stable_key,
            "--json",
        ]
        result = await self.runner(
            argv,
            cwd=self.cwd,
            timeout_seconds=self.timeout_seconds,
        )
        if result.returncode != 0:
            raise _error_from_text(
                result.stderr or result.stdout,
                returncode=result.returncode,
            )
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise LarkCliError(
                "invalid lark-cli reply JSON",
                subtype="invalid_reply_json",
            ) from exc
        message = payload.get("data", payload) if isinstance(payload, dict) else {}
        response_message_id = (
            str(message.get("message_id") or message.get("messageId") or "").strip()
            if isinstance(message, dict)
            else ""
        )
        if not response_message_id:
            raise LarkCliError(
                "lark-cli reply response missing message_id",
                subtype="reply_message_id_missing",
            )
        return response_message_id


async def _create_subprocess_exec(
    *argv: str,
    shell: bool = False,
    **kwargs: object,
) -> asyncio.subprocess.Process:
    if shell:
        raise ValueError("feishu_bot_shell_process_forbidden")
    return await asyncio.create_subprocess_exec(*argv, **kwargs)


async def _run_lark_command(
    argv: list[str],
    *,
    cwd: Path,
    timeout_seconds: float,
) -> LarkCommandResult:
    started = time.monotonic()
    resolved_argv = [*_resolve_lark_cli_prefix(argv[0]), *argv[1:]]
    process = await _create_subprocess_exec(
        *resolved_argv,
        cwd=str(cwd),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_lark_parent_environment(os.environ),
        shell=False,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=max(1.0, timeout_seconds),
        )
    except TimeoutError:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except TimeoutError:
            process.kill()
            await process.wait()
        return LarkCommandResult(
            returncode=124,
            stdout="",
            stderr="lark-cli command timeout",
            elapsed_seconds=time.monotonic() - started,
        )
    return LarkCommandResult(
        returncode=int(process.returncode or 0),
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace")[-4000:],
        elapsed_seconds=time.monotonic() - started,
    )


def _resolve_lark_cli_prefix(
    command: str,
    *,
    platform_name: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    exists: Callable[[Path], bool] | None = None,
) -> list[str]:
    """Resolve npm's node entrypoint on Windows without invoking a shell."""

    active_platform = platform_name or os.name
    if active_platform != "nt" or Path(command).suffix:
        return [command]
    path_exists = exists or (lambda path: path.is_file())
    command_shim = which(f"{command}.cmd")
    if command_shim:
        root = Path(command_shim).parent
        node = root / "node.exe"
        script = root / "node_modules" / "@larksuite" / "cli" / "scripts" / "run.js"
        if path_exists(node) and path_exists(script):
            return [str(node), str(script)]
    executable = which(f"{command}.exe")
    if executable:
        return [executable]
    raise FileNotFoundError(f"feishu_bot_executable_not_found:{command}.exe")


def _lark_parent_environment(
    source: os._Environ[str] | dict[str, str],
) -> dict[str, str]:
    environment = {
        key: value
        for key, value in source.items()
        if key.upper() in _LARK_PARENT_ENV_ALLOW
    }
    environment["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
    environment["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
    return environment


def _error_from_text(
    text: str,
    *,
    returncode: int | None,
    default_message: str = "lark-cli command failed",
    default_subtype: str = "command_failed",
) -> LarkCliError:
    for line in reversed(str(text or "").splitlines()):
        envelope = _error_envelope(line)
        if envelope is not None:
            return _error_from_envelope(envelope, returncode=returncode)
    message = str(text or "").strip()[-1000:] or default_message
    return LarkCliError(
        message,
        subtype=default_subtype,
        returncode=returncode,
    )


def _error_envelope(text: str) -> dict[str, object] | None:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("ok") is not False:
        return None
    error = payload.get("error")
    return error if isinstance(error, dict) else None


def _error_from_envelope(
    error: dict[str, object],
    *,
    returncode: int | None = None,
) -> LarkCliError:
    return LarkCliError(
        str(error.get("message") or "lark-cli command failed"),
        error_type=str(error.get("type") or "lark_cli"),
        subtype=str(error.get("subtype") or "command_failed"),
        details=error,
        returncode=returncode,
    )


def _required_text(value: object, error: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(error)
    return text
