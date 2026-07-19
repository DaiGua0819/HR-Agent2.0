from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOPOLOGY_PATH = SKILL_ROOT / "references" / "topology.json"
ANOMALY_PATTERN = re.compile(
    r"failed|mismatch|ambiguous|stale_|not_closed|blocked|unknown_question|"
    r"unconfigured_position|download_error|security_verification|login_required|"
    r"conversation_changed|identity_changed|changed_before_send",
    re.IGNORECASE,
)
TEXT_OMIT_KEYS = {
    "rawtext",
    "raw_text",
    "summary",
    "bodytext",
    "body_text",
    "headertext",
    "header_text",
}
STOP_ACTIONS = {"send_failed", "request_resume_failed", "escalate"}
LOCAL_RESUME_PLATFORMS = ("job51", "zhilian")


class ManagerError(RuntimeError):
    pass


class AgentManagerRunLock:
    """Hold one OS-backed lock for the full guarded run."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.stream: Any = None

    def __enter__(self) -> AgentManagerRunLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            stream.write(b" ")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            raise ManagerError(f"run_already_active:{self.path}") from error

        stream.seek(0)
        stream.truncate()
        stream.write(
            json.dumps(
                {"pid": os.getpid(), "startedAt": now_iso()},
                ensure_ascii=False,
            ).encode("utf-8")
        )
        stream.flush()
        os.fsync(stream.fileno())
        self.stream = stream
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        stream = self.stream
        self.stream = None
        if stream is None:
            return
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


@dataclass(frozen=True)
class Classification:
    is_anomaly: bool
    reasons: list[str]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def subprocess_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return a child-process environment with deterministic UTF-8 I/O."""

    environment = dict(os.environ if base is None else base)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def configure_standard_streams() -> None:
    """Keep candidate text printable on Windows regardless of the active code page."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            continue


def classify_result(payload: dict[str, Any]) -> Classification:
    reasons: list[str] = []
    if payload.get("accepted") is False:
        reasons.append("accepted_false")
    action = str(payload.get("nextAction") or "")
    stage = str(payload.get("stage") or "")
    if action in STOP_ACTIONS:
        reasons.append(action)

    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    candidates = [
        stage,
        str(decision.get("reason") or ""),
        str(decision.get("failureReason") or ""),
    ]
    result = decision.get("result") if isinstance(decision.get("result"), dict) else {}
    candidates.extend(
        (
            str(result.get("reason") or ""),
            str(result.get("outcome") or ""),
        )
    )
    send_result = (
        decision.get("sendResult") if isinstance(decision.get("sendResult"), dict) else {}
    )
    details = (
        send_result.get("details")
        if isinstance(send_result.get("details"), dict)
        else {}
    )
    candidates.append(str(details.get("reason") or ""))

    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and ANOMALY_PATTERN.search(candidate) and candidate not in reasons:
            reasons.append(candidate)
    return Classification(is_anomaly=bool(reasons), reasons=reasons)


def resume_handling(payload: dict[str, Any]) -> str:
    """Return the platform-aware resume outcome used in operator summaries."""

    platform = str(payload.get("platform") or "").strip().lower()
    next_action = str(payload.get("nextAction") or "").strip()
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    decision_action = str(decision.get("action") or "").strip()
    result = decision.get("result") if isinstance(decision.get("result"), dict) else {}

    if platform == "boss":
        reason = str(result.get("reason") or "").strip()
        outcome = str(result.get("outcome") or "").strip()
        request_verified = bool(result.get("ok")) and (
            next_action == "request_resume" or decision_action == "request_resume"
        )
        if request_verified or reason == "boss_attachment_present_no_local_download" or outcome in {
            "request_confirmed",
            "resume_attachment_received",
            "resume_consent_accepted",
        }:
            return "boss_request_verified_server_imap"

    if bool(result.get("downloaded")):
        return "local_resume_downloaded"
    if (
        next_action == "request_resume" or decision_action == "request_resume"
    ) and bool(result.get("requested") or result.get("confirmed")):
        return "resume_requested_waiting"
    return ""


def canonical_job_label(value: object) -> str:
    """Normalize common report aliases without importing the application runtime."""

    text = str(value or "").strip()
    compact = re.sub(r"[\s+]+", "", text).lower()
    if compact in {"ai产品经理", "aiproductmanager", "aipm"}:
        return "AI产品经理"
    if compact in {"b端社交媒体运营", "运营b"}:
        return "运营B"
    if compact.startswith("企业内容运营负责人") or compact == "运营a":
        return "运营A"
    return text


def sanitize_payload(value: Any, *, key: str = "") -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "bytes", "length": len(value)}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(item_key): sanitize_payload(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, str):
        if key.lower() in TEXT_OMIT_KEYS and len(value) > 300:
            return {"omitted": True, "length": len(value)}
        if len(value) > 4000:
            return {"omitted": True, "length": len(value), "prefix": value[:240]}
    return value


def parse_target(value: str) -> tuple[str, str]:
    owner, separator, platform = value.partition(":")
    owner = owner.strip()
    platform = platform.strip().lower()
    if not separator or not owner or platform not in {"boss", "job51", "zhilian"}:
        raise ValueError(f"invalid target: {value!r}; expected OWNER:PLATFORM")
    return owner, platform


def request_stop(path: Path, *, reason: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"requestedAt": now_iso(), "reason": reason}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def stop_requested(path: Path) -> bool:
    return path.exists()


def clear_stop(path: Path) -> None:
    path.unlink(missing_ok=True)


def load_topology(path: Path | None = None) -> dict[str, Any]:
    target = path or DEFAULT_TOPOLOGY_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    for key in (
        "projectRoot",
        "pythonExecutable",
        "browserExecutable",
        "databasePath",
        "controlPlane",
        "owners",
    ):
        if not payload.get(key):
            raise ManagerError(f"topology_missing_{key}")
    return payload


def runtime_dir(topology: dict[str, Any]) -> Path:
    return Path(topology["projectRoot"]) / "data" / "agent_manager"


def topology_owner(topology: dict[str, Any], owner: str) -> dict[str, Any]:
    for item in topology["owners"]:
        if item.get("owner") == owner:
            return item
    raise ManagerError(f"unknown_owner:{owner}")


def http_json(
    url: str,
    *,
    method: str = "GET",
    timeout: float = 10,
) -> Any:
    request = urllib.request.Request(
        url,
        method=method,
        headers={"Accept": "application/json", "User-Agent": "recruit-agent-manager/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise ManagerError(f"http_{error.code}:{url}:{body[:800]}") from error
    except Exception as error:
        raise ManagerError(f"http_error:{url}:{error}") from error
    text = raw.decode("utf-8", errors="replace")
    return json.loads(text) if text.strip() else {}


def listener_info(port: int) -> dict[str, Any] | None:
    script = (
        f"$c=Get-NetTCPConnection -LocalPort {port} -State Listen "
        "-ErrorAction SilentlyContinue|Select-Object -First 1;"
        "if($c){$p=Get-CimInstance Win32_Process -Filter "
        "\"ProcessId=$($c.OwningProcess)\";"
        "[pscustomobject]@{pid=[int]$c.OwningProcess;parentPid=[int]$p.ParentProcessId;"
        "name=$p.Name;commandLine=$p.CommandLine}|ConvertTo-Json -Compress}"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = completed.stdout.strip()
    return json.loads(output) if output else None


def git_info(project_root: Path) -> dict[str, Any]:
    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(project_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return completed.stdout.strip()

    return {
        "branch": git("branch", "--show-current"),
        "commit": git("rev-parse", "--short", "HEAD"),
        "status": git("status", "--short", "--branch").splitlines(),
    }


def configured_settings(topology: dict[str, Any]) -> dict[str, Any]:
    project_root = Path(topology["projectRoot"])
    environment = subprocess_environment()
    for key in ("DRY_RUN", "DATABASE_PATH", "CONTROL_PLANE_PORT"):
        environment.pop(key, None)
    environment["PYTHONPATH"] = str(project_root)
    code = (
        "import json; from app.settings import load_settings; "
        "s=load_settings(); print(json.dumps({"
        "'databasePath':str(s.resolved_database_path),'dryRun':bool(s.dry_run)"
        "},ensure_ascii=False))"
    )
    completed = subprocess.run(
        [topology["pythonExecutable"], "-c", code],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise ManagerError(f"settings_probe_failed:{completed.stderr[-1000:]}")
    return json.loads(completed.stdout.strip().splitlines()[-1])


def database_info(topology: dict[str, Any], *, quick_check: bool = False) -> dict[str, Any]:
    path = Path(topology["databasePath"])
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "size": path.stat().st_size if path.exists() else 0,
        "modifiedAt": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        if path.exists()
        else "",
    }
    if quick_check and path.exists():
        uri = f"file:{path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=10) as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
        result["quickCheck"] = str(row[0] if row else "")
    return result


def cdp_inventory(item: dict[str, Any]) -> dict[str, Any]:
    port = int(item["cdpPort"])
    base = f"http://127.0.0.1:{port}"
    result: dict[str, Any] = {"port": port, "ready": False, "pages": [], "blockers": []}
    try:
        result["version"] = http_json(f"{base}/json/version", timeout=3)
        pages = http_json(f"{base}/json/list", timeout=3)
    except ManagerError as error:
        result["error"] = str(error)
        return result
    result["ready"] = True
    result["pages"] = [
        {"title": str(page.get("title") or ""), "url": str(page.get("url") or "")}
        for page in pages
        if page.get("type") == "page"
    ]
    for platform in ("boss", "job51", "zhilian"):
        matches = matching_pages(result["pages"], platform)
        if not matches:
            result["blockers"].append(
                {"platform": platform, "reason": "platform_page_missing"}
            )
            continue
        for page in matches:
            blocker = page_blocker(platform, page)
            if blocker:
                result["blockers"].append({"platform": platform, **blocker})
    return result


def matching_pages(pages: list[dict[str, str]], platform: str) -> list[dict[str, str]]:
    markers = {
        "boss": ("zhipin.com",),
        "job51": ("ehire.51job.com/revision/chat",),
        "zhilian": ("rd6.zhaopin.com/app/im",),
    }[platform]
    return [
        page
        for page in pages
        if any(marker in page.get("url", "").lower() for marker in markers)
    ]


def page_blocker(platform: str, page: dict[str, str]) -> dict[str, str] | None:
    title = page.get("title", "").lower()
    url = page.get("url", "").lower()
    if platform == "boss" and (
        "verify.html" in url
        or "/passport/" in url
        or "安全验证" in page.get("title", "")
        or "security" in title
    ):
        return {"reason": "security_verification_required", "url": page.get("url", "")}
    if any(marker in url for marker in ("login", "signin", "passport", "/s/login")):
        return {"reason": "login_required", "url": page.get("url", "")}
    return None


def worker_status(item: dict[str, Any]) -> dict[str, Any]:
    port = int(item["workerPort"])
    try:
        return http_json(f"http://127.0.0.1:{port}/status", timeout=5)
    except ManagerError as error:
        return {"status": "unreachable", "port": port, "error": str(error)}


def control_health(topology: dict[str, Any]) -> dict[str, Any]:
    port = int(topology["controlPlane"]["port"])
    try:
        return http_json(f"http://127.0.0.1:{port}/health", timeout=8)
    except ManagerError as error:
        return {"status": "unreachable", "port": port, "error": str(error)}


def build_inventory(topology: dict[str, Any], *, quick_check: bool = False) -> dict[str, Any]:
    project_root = Path(topology["projectRoot"])
    owners: list[dict[str, Any]] = []
    for item in topology["owners"]:
        owners.append(
            {
                "owner": item["owner"],
                "profileDir": str(item["profileDir"]),
                "profileExists": Path(item["profileDir"]).is_dir(),
                "cdp": cdp_inventory(item),
                "worker": worker_status(item),
                "workerListener": listener_info(int(item["workerPort"])),
            }
        )
    return {
        "generatedAt": now_iso(),
        "projectRoot": str(project_root),
        "git": git_info(project_root),
        "configuredSettings": configured_settings(topology),
        "database": database_info(topology, quick_check=quick_check),
        "controlPlane": control_health(topology),
        "controlListener": listener_info(int(topology["controlPlane"]["port"])),
        "owners": owners,
    }


def preflight(
    topology: dict[str, Any],
    *,
    skipped: set[tuple[str, str]],
    quick_check: bool = False,
    require_runtime: bool = True,
) -> dict[str, Any]:
    inventory = build_inventory(topology, quick_check=quick_check)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    git = inventory["git"]
    if git.get("branch") != topology.get("requiredBranch"):
        errors.append(
            {
                "reason": "wrong_branch",
                "expected": topology.get("requiredBranch"),
                "actual": git.get("branch"),
            }
        )
    settings = inventory["configuredSettings"]
    expected_db = str(Path(topology["databasePath"]).resolve()).lower()
    actual_db = str(Path(settings["databasePath"]).resolve()).lower()
    if expected_db != actual_db:
        errors.append({"reason": "wrong_database", "expected": expected_db, "actual": actual_db})
    if settings.get("dryRun"):
        errors.append({"reason": "configured_dry_run_true"})
    if not inventory["database"].get("exists"):
        errors.append({"reason": "database_missing"})
    if quick_check and inventory["database"].get("quickCheck") != "ok":
        errors.append(
            {
                "reason": "database_quick_check_failed",
                "actual": inventory["database"].get("quickCheck"),
            }
        )

    if require_runtime and inventory["controlPlane"].get("status") != "ok":
        errors.append({"reason": "control_plane_not_ready"})
    for owner_item in inventory["owners"]:
        owner = owner_item["owner"]
        if not owner_item["profileExists"]:
            errors.append({"owner": owner, "reason": "profile_missing"})
        if not owner_item["cdp"].get("ready"):
            errors.append({"owner": owner, "reason": "cdp_not_ready"})
        if require_runtime:
            status = owner_item["worker"]
            if not (
                status.get("status") == "ready"
                and status.get("cdpReady") is True
                and status.get("browserBackend") == "cloak"
                and status.get("dryRun") is False
            ):
                errors.append({"owner": owner, "reason": "worker_not_live_ready", "status": status})
        for blocker in owner_item["cdp"].get("blockers", []):
            target = (owner, blocker["platform"])
            payload = {"owner": owner, **blocker}
            if target in skipped:
                warnings.append({**payload, "skipped": True})
            else:
                errors.append(payload)
    return {"ok": not errors, "errors": errors, "warnings": warnings, "inventory": inventory}


def wait_for_url(url: str, *, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            http_json(url, timeout=4)
            return
        except ManagerError:
            time.sleep(2)
    raise ManagerError(f"service_start_timeout:{url}")


def browser_command(topology: dict[str, Any], item: dict[str, Any]) -> list[str]:
    return [
        str(topology["browserExecutable"]),
        f"--remote-debugging-port={int(item['cdpPort'])}",
        "--remote-allow-origins=*",
        f"--user-data-dir={item['profileDir']}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--disable-background-mode",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "about:blank",
    ]


def launch_browser(topology: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    executable = Path(topology["browserExecutable"])
    profile_dir = Path(item["profileDir"])
    if not executable.is_file():
        raise ManagerError(f"cloak_browser_executable_missing:{executable}")
    if not profile_dir.is_dir():
        raise ManagerError(f"profile_missing:{item['owner']}:{profile_dir}")
    command = browser_command(topology, item)
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=executable.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
        close_fds=True,
    )
    wait_for_url(
        f"http://127.0.0.1:{int(item['cdpPort'])}/json/version",
        timeout=60,
    )
    return {
        "started": True,
        "wrapperPid": process.pid,
        "cdpPort": int(item["cdpPort"]),
        "profileDir": str(profile_dir),
        "startedAt": now_iso(),
    }


def process_matches(listener: dict[str, Any] | None, marker: str) -> bool:
    return bool(listener and marker.lower() in str(listener.get("commandLine") or "").lower())


def launch_process(
    topology: dict[str, Any],
    *,
    arguments: list[str],
    log_prefix: str,
    extra_env: dict[str, str],
) -> dict[str, Any]:
    project_root = Path(topology["projectRoot"])
    logs = runtime_dir(topology) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stdout_path = logs / f"{log_prefix}_{stamp}.out.log"
    stderr_path = logs / f"{log_prefix}_{stamp}.err.log"
    environment = subprocess_environment()
    environment.update(extra_env)
    environment["PYTHONPATH"] = str(project_root)
    creation_flags = 0
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        process = subprocess.Popen(
            [topology["pythonExecutable"], *arguments],
            cwd=project_root,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            creationflags=creation_flags,
            close_fds=True,
        )
    return {
        "wrapperPid": process.pid,
        "arguments": arguments,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "startedAt": now_iso(),
    }


def start_runtime(topology: dict[str, Any], *, adopt_running: bool) -> dict[str, Any]:
    records: dict[str, Any] = {"startedAt": now_iso(), "projectRoot": topology["projectRoot"]}
    for item in topology["owners"]:
        cdp = cdp_inventory(item)
        if cdp.get("ready"):
            records[f"browser:{item['owner']}"] = {
                "adopted": True,
                "cdpPort": int(item["cdpPort"]),
                "profileDir": str(item["profileDir"]),
            }
            continue
        records[f"browser:{item['owner']}"] = launch_browser(topology, item)

    for item in topology["owners"]:
        port = int(item["workerPort"])
        listener = listener_info(port)
        if listener:
            status = worker_status(item)
            if not adopt_running:
                raise ManagerError(f"worker_already_running_unmanaged:{item['owner']}:{port}")
            if status.get("status") != "ready":
                raise ManagerError(f"worker_running_but_unhealthy:{item['owner']}:{status}")
            records[f"worker:{item['owner']}"] = {"adopted": True, "listener": listener}
            continue
        record = launch_process(
            topology,
            arguments=["run_worker.py", "--owner", item["owner"], "--port", str(port)],
            log_prefix=f"worker_{item['slug']}",
            extra_env={"HR_AGENT_BROWSER_BACKEND": "cloak", "DRY_RUN": "false"},
        )
        wait_for_url(f"http://127.0.0.1:{port}/status")
        record["listener"] = listener_info(port)
        records[f"worker:{item['owner']}"] = record

    control_port = int(topology["controlPlane"]["port"])
    listener = listener_info(control_port)
    if listener:
        health = control_health(topology)
        if not adopt_running:
            raise ManagerError(f"control_plane_already_running_unmanaged:{control_port}")
        if health.get("status") != "ok":
            raise ManagerError(f"control_plane_running_but_unhealthy:{health}")
        records["controlPlane"] = {"adopted": True, "listener": listener}
    else:
        record = launch_process(
            topology,
            arguments=["run_control_plane.py"],
            log_prefix=f"control_{control_port}",
            extra_env={"CONTROL_PLANE_PORT": str(control_port)},
        )
        wait_for_url(f"http://127.0.0.1:{control_port}/health")
        record["listener"] = listener_info(control_port)
        records["controlPlane"] = record

    target = runtime_dir(topology) / "managed_processes.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


def configured_targets(
    topology: dict[str, Any],
    requested: list[str],
) -> list[tuple[str, str]]:
    if requested:
        return [parse_target(item) for item in requested]
    return [parse_target(item) for item in topology["runOrder"]]


def targets_by_owner(
    targets: Iterable[tuple[str, str]],
) -> list[tuple[str, list[str]]]:
    """Keep each owner's platform order while allowing owners to run in parallel."""

    grouped: dict[str, list[str]] = {}
    for owner, platform in targets:
        grouped.setdefault(owner, []).append(platform)
    return list(grouped.items())


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(sanitize_payload(payload), ensure_ascii=False) + "\n")


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Replace a JSON state file without exposing a partially written document."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for attempt in range(50):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt >= 49:
                    raise
                time.sleep(0.01)
    finally:
        temporary.unlink(missing_ok=True)


def concise_result(payload: dict[str, Any]) -> dict[str, Any]:
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    result = decision.get("result") if isinstance(decision.get("result"), dict) else {}
    return {
        "processed": int(payload.get("processed") or 0),
        "conversationId": str(payload.get("conversationId") or ""),
        "selectedConversationId": str(payload.get("selectedConversationId") or ""),
        "selectedProcessingKey": str(payload.get("selectedProcessingKey") or ""),
        "nextAction": str(payload.get("nextAction") or ""),
        "stage": str(payload.get("stage") or ""),
        "resultReason": str(result.get("reason") or ""),
        "resumeHandling": resume_handling(payload),
    }


def update_run_counters(
    run_state: dict[str, Any],
    summary: dict[str, Any],
    classification: Classification,
) -> None:
    processed = max(0, int(summary.get("processed") or 0))
    run_state["processed"] = int(run_state.get("processed") or 0) + processed
    if classification.is_anomaly:
        run_state["anomalies"] = int(run_state.get("anomalies") or 0) + 1


def _run_guarded(
    topology: dict[str, Any],
    *,
    targets: list[tuple[str, str]],
    skipped: set[tuple[str, str]],
    max_contacts: int,
    max_anomalies: int,
    sleep_seconds: float,
) -> dict[str, Any]:
    check = preflight(topology, skipped=skipped, require_runtime=True)
    if not check["ok"]:
        raise ManagerError(f"preflight_failed:{json.dumps(check['errors'], ensure_ascii=False)}")

    state_dir = runtime_dir(topology)
    stop_path = state_dir / "stop.requested"
    clear_stop(stop_path)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    log_path = state_dir / "runs" / f"{run_id}.jsonl"
    current_path = state_dir / "current_run.json"
    run_state: dict[str, Any] = {
        "runId": run_id,
        "status": "running",
        "startedAt": now_iso(),
        "targets": [f"{owner}:{platform}" for owner, platform in targets],
        "skipped": [f"{owner}:{platform}" for owner, platform in sorted(skipped)],
        "logPath": str(log_path),
        "processed": 0,
        "anomalies": 0,
    }
    write_json_atomic(current_path, run_state)
    control_port = int(topology["controlPlane"]["port"])
    state_lock = threading.Lock()
    stop_event = threading.Event()

    def persist_state() -> None:
        write_json_atomic(current_path, run_state)

    def set_stop_status(status: str) -> None:
        with state_lock:
            if run_state["status"] == "running":
                run_state["status"] = status
                persist_state()
            stop_event.set()

    def claim_contact_dispatch() -> bool:
        with state_lock:
            if stop_requested(stop_path):
                if run_state["status"] == "running":
                    run_state["status"] = "stop_requested"
                    persist_state()
                stop_event.set()
                return False
            return run_state["status"] == "running" and not stop_event.is_set()

    def record_page_blocker(
        owner: str,
        platform: str,
        blockers: list[dict[str, Any]],
    ) -> bool:
        event = {
            "timestamp": now_iso(),
            "event": "page_blocked",
            "owner": owner,
            "platform": platform,
            "blockers": blockers,
        }
        with state_lock:
            run_state["anomalies"] += 1
            append_jsonl(log_path, event)
            print(json.dumps(event, ensure_ascii=False), flush=True)
            exceeded = run_state["anomalies"] > max_anomalies
            if exceeded and run_state["status"] == "running":
                run_state["status"] = "stopped_on_anomaly"
                stop_event.set()
            persist_state()
        return exceeded

    def record_contact_result(
        *,
        owner: str,
        platform: str,
        elapsed: float,
        payload: dict[str, Any],
        classification: Classification,
        summary: dict[str, Any],
    ) -> bool:
        event = {
            "timestamp": now_iso(),
            "event": "contact_result",
            "owner": owner,
            "platform": platform,
            "elapsedSeconds": elapsed,
            "classification": asdict(classification),
            "summary": summary,
            "response": payload,
        }
        with state_lock:
            append_jsonl(log_path, event)
            print(
                json.dumps(
                    {
                        "owner": owner,
                        "platform": platform,
                        "elapsedSeconds": elapsed,
                        **summary,
                        "anomalyReasons": classification.reasons,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            update_run_counters(run_state, summary, classification)
            exceeded = (
                classification.is_anomaly
                and run_state["anomalies"] > max_anomalies
            )
            if exceeded and run_state["status"] == "running":
                run_state["status"] = "stopped_on_anomaly"
                stop_event.set()
            persist_state()
        return exceeded

    def run_owner_lane(owner: str, platforms: list[str]) -> None:
        try:
            owner_config = topology_owner(topology, owner)
            for platform in platforms:
                if stop_event.is_set():
                    return
                if (owner, platform) in skipped:
                    with state_lock:
                        append_jsonl(
                            log_path,
                            {
                                "timestamp": now_iso(),
                                "event": "target_skipped",
                                "owner": owner,
                                "platform": platform,
                            },
                        )
                    continue

                count = 0
                excluded_contact_ids: set[str] = set()
                while max_contacts <= 0 or count < max_contacts:
                    if stop_event.is_set():
                        return
                    if stop_requested(stop_path):
                        set_stop_status("stop_requested")
                        return

                    cdp = cdp_inventory(owner_config)
                    active_blockers = [
                        blocker
                        for blocker in cdp.get("blockers", [])
                        if blocker.get("platform") == platform
                    ]
                    if active_blockers:
                        record_page_blocker(owner, platform, active_blockers)
                        break

                    worker = worker_status(owner_config)
                    if worker.get("agentBusy"):
                        stop_event.wait(2)
                        continue
                    if not claim_contact_dispatch():
                        return

                    query = urllib.parse.urlencode(
                        [
                            ("owner", owner),
                            ("batch_id", run_id),
                            *(
                                ("exclude_conversation_id", conversation_id)
                                for conversation_id in sorted(excluded_contact_ids)
                            ),
                        ]
                    )
                    url = (
                        f"http://127.0.0.1:{control_port}/automation/{platform}/"
                        f"process-messages?{query}"
                    )
                    started = time.monotonic()
                    try:
                        payload = http_json(url, method="POST", timeout=650)
                    except ManagerError as error:
                        classification = Classification(True, [str(error)])
                        payload = {"accepted": False, "error": str(error)}
                    else:
                        classification = classify_result(payload)
                    elapsed = round(time.monotonic() - started, 1)
                    summary = concise_result(payload)
                    exceeded = record_contact_result(
                        owner=owner,
                        platform=platform,
                        elapsed=elapsed,
                        payload=payload,
                        classification=classification,
                        summary=summary,
                    )
                    processed_key = str(summary.get("selectedProcessingKey") or "").strip()
                    if summary["processed"] > 0 and processed_key:
                        excluded_contact_ids.add(processed_key)
                    if classification.is_anomaly:
                        if exceeded:
                            return
                        skipped_contact_id = str(
                            processed_key
                            or summary.get("selectedConversationId")
                            or summary.get("conversationId")
                            or ""
                        ).strip()
                        if summary["processed"] > 0 and skipped_contact_id:
                            excluded_contact_ids.add(skipped_contact_id)
                            count += summary["processed"]
                            if sleep_seconds > 0:
                                stop_event.wait(sleep_seconds)
                            continue
                        break
                    if summary["processed"] == 0:
                        break
                    count += summary["processed"]
                    if sleep_seconds > 0:
                        stop_event.wait(sleep_seconds)
        except BaseException:
            stop_event.set()
            raise

    try:
        owner_lanes = targets_by_owner(targets)
        with ThreadPoolExecutor(
            max_workers=max(1, len(owner_lanes)),
            thread_name_prefix="recruit-owner",
        ) as executor:
            futures = {
                executor.submit(run_owner_lane, owner, platforms): owner
                for owner, platforms in owner_lanes
            }
            for future in as_completed(futures):
                future.result()
        with state_lock:
            if run_state["status"] == "running":
                run_state["status"] = "complete"
        return run_state
    except BaseException as error:
        with state_lock:
            run_state["status"] = "failed"
            run_state["error"] = str(error)[:800] or type(error).__name__
        raise
    finally:
        run_state["finishedAt"] = now_iso()
        write_json_atomic(current_path, run_state)
        append_jsonl(
            log_path,
            {"timestamp": now_iso(), "event": "run_finished", "state": run_state},
        )


def run_guarded(
    topology: dict[str, Any],
    *,
    targets: list[tuple[str, str]],
    skipped: set[tuple[str, str]],
    max_contacts: int,
    max_anomalies: int,
    sleep_seconds: float,
) -> dict[str, Any]:
    state_dir = runtime_dir(topology)
    with AgentManagerRunLock(state_dir / "run.lock"):
        return _run_guarded(
            topology,
            targets=targets,
            skipped=skipped,
            max_contacts=max_contacts,
            max_anomalies=max_anomalies,
            sleep_seconds=sleep_seconds,
        )


def tail_jsonl(path: Path, limit: int) -> list[Any]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    return [json.loads(line) for line in lines if line.strip()]


def status_payload(topology: dict[str, Any], *, tail: int = 8) -> dict[str, Any]:
    state_dir = runtime_dir(topology)
    current_path = state_dir / "current_run.json"
    current = (
        json.loads(current_path.read_text(encoding="utf-8")) if current_path.exists() else {}
    )
    log_path = Path(str(current.get("logPath") or "")) if current.get("logPath") else None
    return {
        "generatedAt": now_iso(),
        "controlPlane": control_health(topology),
        "workers": [worker_status(item) for item in topology["owners"]],
        "currentRun": current,
        "stopRequested": stop_requested(state_dir / "stop.requested"),
        "recentEvents": tail_jsonl(log_path, tail) if log_path else [],
    }


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    if not _table_exists(connection, table):
        return 0
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _table_max(connection: sqlite3.Connection, table: str, column: str) -> str:
    if not _table_exists(connection, table):
        return ""
    value = connection.execute(f"SELECT MAX({column}) FROM {table}").fetchone()[0]
    return str(value or "")


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def data_health_payload(topology: dict[str, Any]) -> dict[str, Any]:
    """Read local persistence and sync health without touching platform pages."""

    project_root = Path(topology["projectRoot"])
    database_path = Path(
        topology.get("databasePath") or project_root / "data" / "resumes.sqlite"
    ).resolve()
    if not database_path.exists():
        raise ManagerError(f"database_not_found:{database_path}")

    uri = f"file:{database_path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        artifact_status = {"parsed": 0, "pending": 0, "failed": 0}
        artifact_total = 0
        unique_files = 0
        pending_by_platform_job: list[dict[str, Any]] = []
        recent_artifacts = 0
        if _table_exists(connection, "resume_artifacts"):
            artifact_total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM resume_artifacts "
                    "WHERE platform IN (?, ?)",
                    LOCAL_RESUME_PLATFORMS,
                ).fetchone()[0]
            )
            for row in connection.execute(
                "SELECT parse_status, COUNT(*) AS count "
                "FROM resume_artifacts WHERE platform IN (?, ?) "
                "GROUP BY parse_status",
                LOCAL_RESUME_PLATFORMS,
            ):
                artifact_status[str(row["parse_status"] or "unknown")] = int(row["count"])
            unique_files = int(
                connection.execute(
                    "SELECT COUNT(DISTINCT file_hash) FROM resume_artifacts "
                    "WHERE platform IN (?, ?) AND COALESCE(file_hash, '') <> ''",
                    LOCAL_RESUME_PLATFORMS,
                ).fetchone()[0]
            )
            cutoff = (datetime.now(UTC) - timedelta(days=1)).isoformat()
            recent_artifacts = int(
                connection.execute(
                    "SELECT COUNT(*) FROM resume_artifacts "
                    "WHERE platform IN (?, ?) AND created_at >= ?",
                    (*LOCAL_RESUME_PLATFORMS, cutoff),
                ).fetchone()[0]
            )
            if _table_exists(connection, "conversation_sessions"):
                pending_rows = connection.execute(
                    """
                    SELECT
                      ra.platform AS platform,
                      COALESCE(
                        NULLIF(cs.applied_position, ''),
                        NULLIF(cs.position, ''),
                        ra.position,
                        ''
                      ) AS job,
                      COUNT(*) AS count
                    FROM resume_artifacts AS ra
                    LEFT JOIN conversation_sessions AS cs ON cs.id = ra.session_id
                    WHERE ra.platform IN (?, ?) AND ra.parse_status = 'pending'
                    GROUP BY ra.platform, job
                    ORDER BY count DESC, ra.platform, job
                    """,
                    LOCAL_RESUME_PLATFORMS,
                )
            else:
                pending_rows = connection.execute(
                    """
                    SELECT platform, COALESCE(position, '') AS job, COUNT(*) AS count
                    FROM resume_artifacts
                    WHERE platform IN (?, ?) AND parse_status = 'pending'
                    GROUP BY platform, job
                    ORDER BY count DESC, platform, job
                    """,
                    LOCAL_RESUME_PLATFORMS,
                )
            grouped_pending: dict[tuple[str, str], int] = {}
            for row in pending_rows:
                key = (
                    str(row["platform"] or ""),
                    canonical_job_label(row["job"]),
                )
                grouped_pending[key] = grouped_pending.get(key, 0) + int(row["count"])
            pending_by_platform_job = [
                {"platform": platform, "job": job, "count": count}
                for (platform, job), count in sorted(
                    grouped_pending.items(),
                    key=lambda item: (-item[1], item[0][0], item[0][1]),
                )
            ]

        sync_dir = project_root / "data" / "sync"
        sync_state_path = sync_dir / "auto_sync_state.json"
        sync_state = _read_json_object(sync_state_path)
        pending_dir = sync_dir / "pending"
        pending_batches = (
            len(list(pending_dir.glob("*.json"))) if pending_dir.exists() else 0
        )
        return {
            "generatedAt": now_iso(),
            "databasePath": str(database_path),
            "conversations": {
                "sessions": _table_count(connection, "conversation_sessions"),
                "messages": _table_count(connection, "conversation_messages"),
                "lastSessionUpdatedAt": _table_max(
                    connection, "conversation_sessions", "updated_at"
                ),
                "lastMessageCreatedAt": _table_max(
                    connection, "conversation_messages", "created_at"
                ),
            },
            "localResumePipeline": {
                "scope": ["job51", "zhilian"],
                "artifacts": {
                    "total": artifact_total,
                    "uniqueFiles": unique_files,
                    "last24Hours": recent_artifacts,
                    "byStatus": artifact_status,
                    "lastCreatedAt": _table_max(
                        connection, "resume_artifacts", "created_at"
                    ),
                },
                "pendingByPlatformJob": pending_by_platform_job,
                "resumes": {
                    "total": _table_count(connection, "resumes"),
                    "lastUpdatedAt": _table_max(connection, "resumes", "updated_at"),
                },
            },
            "bossContract": {
                "completion": "verified_request_is_successful_resume_acquisition",
                "localFileRequired": False,
                "localImapRequired": False,
                "delivery": "production_server_imap",
            },
            "autoSync": {
                "statePath": str(sync_state_path),
                "lastSuccessAt": str(sync_state.get("lastSuccessAt") or ""),
                "lastError": str(sync_state.get("lastError") or ""),
                "consecutiveFailures": int(sync_state.get("consecutiveFailures") or 0),
                "pendingBatches": pending_batches,
            },
        }
    finally:
        connection.close()


def _parse_iso_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _daily_utc_bounds(date_text: str, timezone_name: str) -> tuple[datetime, datetime]:
    try:
        zone = (
            timezone(timedelta(hours=8), name="Asia/Shanghai")
            if timezone_name == "Asia/Shanghai"
            else ZoneInfo(timezone_name)
        )
        local_start = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=zone)
    except (ValueError, KeyError) as error:
        raise ManagerError(f"invalid_report_date_or_timezone:{error}") from error
    return local_start.astimezone(UTC), (local_start + timedelta(days=1)).astimezone(UTC)


def daily_report_payload(
    topology: dict[str, Any],
    *,
    date_text: str,
    timezone_name: str = "Asia/Shanghai",
) -> dict[str, Any]:
    """Build a read-only daily report using platform-aware resume semantics."""

    project_root = Path(topology["projectRoot"])
    database_path = Path(
        topology.get("databasePath") or project_root / "data" / "resumes.sqlite"
    ).resolve()
    if not database_path.exists():
        raise ManagerError(f"database_not_found:{database_path}")
    start, end = _daily_utc_bounds(date_text, timezone_name)

    uri = f"file:{database_path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        if not _table_exists(connection, "conversation_sessions"):
            raise ManagerError("conversation_sessions_table_missing")
        sessions = [dict(row) for row in connection.execute("SELECT * FROM conversation_sessions")]
        sessions_by_conversation: dict[tuple[str, str], list[dict[str, Any]]] = {}
        sessions_by_id: dict[str, dict[str, Any]] = {}
        for session in sessions:
            key = (
                str(session.get("platform") or "").strip().lower(),
                str(session.get("platform_conversation_id") or ""),
            )
            sessions_by_conversation.setdefault(key, []).append(session)
            sessions_by_id[str(session.get("id") or "")] = session

        latest_contacts: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        manager_contact_events = 0
        unmapped_contacts = 0
        runs_dir = project_root / "data" / "agent_manager" / "runs"
        for path in sorted(runs_dir.glob("*.jsonl")) if runs_dir.exists() else []:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict) or event.get("event") != "contact_result":
                    continue
                timestamp = _parse_iso_datetime(event.get("timestamp"))
                if timestamp is None or not (start <= timestamp < end):
                    continue
                summary = event.get("summary") if isinstance(event.get("summary"), dict) else {}
                if int(summary.get("processed") or 0) != 1:
                    continue
                manager_contact_events += 1
                platform = str(event.get("platform") or "").strip().lower()
                conversation_id = str(summary.get("conversationId") or "")
                candidates = sessions_by_conversation.get((platform, conversation_id), [])
                if not candidates:
                    unmapped_contacts += 1
                    continue

                def session_distance(
                    session: dict[str, Any],
                    reference: datetime = timestamp,
                ) -> float:
                    seen = _parse_iso_datetime(
                        session.get("last_seen_at") or session.get("updated_at")
                    )
                    return abs((seen - reference).total_seconds()) if seen else float("inf")

                session = min(candidates, key=session_distance)
                owner = str(session.get("owner") or event.get("owner") or "")
                candidate_name = str(session.get("candidate_name") or "").strip()
                job = canonical_job_label(
                    session.get("applied_position") or session.get("position")
                )
                dedupe_key = (platform, owner, candidate_name, job)
                current = latest_contacts.get(dedupe_key)
                if current is None or timestamp > current["timestamp"]:
                    latest_contacts[dedupe_key] = {
                        "timestamp": timestamp,
                        "platform": platform,
                        "job": job,
                        "event": event,
                    }

        rows: dict[tuple[str, str], dict[str, Any]] = {}

        def report_row(job: str, platform: str) -> dict[str, Any]:
            key = (job, platform)
            if key not in rows:
                rows[key] = {
                    "job": job,
                    "platform": platform,
                    "processedContacts": 0,
                    "bossHandoffs": 0,
                    "localUniqueFiles": 0,
                    "businessResumeAcquisitions": 0,
                    "resumeRequestsWaiting": 0,
                    "anomalies": 0,
                }
            return rows[key]

        for contact in latest_contacts.values():
            event = contact["event"]
            row = report_row(contact["job"], contact["platform"])
            row["processedContacts"] += 1
            response = event.get("response") if isinstance(event.get("response"), dict) else {}
            response = dict(response)
            response.setdefault("platform", contact["platform"])
            handling = resume_handling(response)
            if handling == "boss_request_verified_server_imap":
                row["bossHandoffs"] += 1
            elif handling == "resume_requested_waiting":
                row["resumeRequestsWaiting"] += 1
            classification = (
                event.get("classification")
                if isinstance(event.get("classification"), dict)
                else {}
            )
            if bool(classification.get("is_anomaly")):
                row["anomalies"] += 1

        seen_hashes: set[str] = set()
        if _table_exists(connection, "resume_artifacts"):
            artifact_rows = connection.execute(
                """
                SELECT ra.*, cs.applied_position, cs.position AS session_position
                FROM resume_artifacts AS ra
                LEFT JOIN conversation_sessions AS cs ON cs.id = ra.session_id
                WHERE ra.platform IN (?, ?) AND ra.created_at >= ? AND ra.created_at < ?
                ORDER BY ra.created_at, ra.id
                """,
                (*LOCAL_RESUME_PLATFORMS, start.isoformat(), end.isoformat()),
            )
            for artifact in artifact_rows:
                file_hash = str(artifact["file_hash"] or "")
                if not file_hash or file_hash in seen_hashes:
                    continue
                seen_hashes.add(file_hash)
                platform = str(artifact["platform"] or "").strip().lower()
                job = canonical_job_label(
                    artifact["applied_position"]
                    or artifact["session_position"]
                    or artifact["position"]
                )
                report_row(job, platform)["localUniqueFiles"] += 1

        by_job_platform = []
        for row in rows.values():
            row["businessResumeAcquisitions"] = (
                row["bossHandoffs"] + row["localUniqueFiles"]
            )
            by_job_platform.append(row)
        by_job_platform.sort(key=lambda row: (row["job"], row["platform"]))
        totals = {
            key: sum(int(row[key]) for row in by_job_platform)
            for key in (
                "processedContacts",
                "bossHandoffs",
                "localUniqueFiles",
                "businessResumeAcquisitions",
                "resumeRequestsWaiting",
                "anomalies",
            )
        }
        return {
            "date": date_text,
            "timezone": timezone_name,
            "utcRange": {"start": start.isoformat(), "end": end.isoformat()},
            "totals": totals,
            "byJobPlatform": by_job_platform,
            "unmappedContacts": unmapped_contacts,
            "coverage": {
                "source": "agent_manager_run_jsonl_plus_resume_artifacts",
                "managerContactEvents": manager_contact_events,
                "deduplicatedManagerContacts": len(latest_contacts),
                "note": (
                    "Contacts processed by legacy/direct scripts without agent-manager JSONL "
                    "are not included in processedContacts; local files are still counted "
                    "from artifacts."
                ),
            },
            "countingContract": {
                "processedContacts": "latest contact per platform-owner-candidate-job",
                "bossHandoffs": "verified BOSS requests counted as resume acquisitions",
                "localUniqueFiles": "distinct 51job/Zhilian file hashes created in range",
                "businessResumeAcquisitions": "bossHandoffs + localUniqueFiles",
            },
        }
    finally:
        connection.close()


def print_json(value: Any) -> None:
    print(json.dumps(sanitize_payload(value), ensure_ascii=False, indent=2))


def parse_targets(values: Iterable[str]) -> set[tuple[str, str]]:
    return {parse_target(value) for value in values}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage local recruitment message agents")
    parser.add_argument("--topology", type=Path, default=DEFAULT_TOPOLOGY_PATH)
    sub = parser.add_subparsers(dest="command", required=True)

    inventory_parser = sub.add_parser("inventory")
    inventory_parser.add_argument("--quick-check", action="store_true")

    preflight_parser = sub.add_parser("preflight")
    preflight_parser.add_argument("--skip", action="append", default=[])
    preflight_parser.add_argument("--quick-check", action="store_true")
    preflight_parser.add_argument("--runtime-optional", action="store_true")

    start_parser = sub.add_parser("start")
    start_parser.add_argument("--adopt-running", action="store_true")

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--target", action="append", default=[])
    run_parser.add_argument("--skip", action="append", default=[])
    run_parser.add_argument("--max-contacts", type=int, default=20)
    run_parser.add_argument("--max-anomalies", type=int, default=0)
    run_parser.add_argument("--sleep", type=float, default=2.0)

    status_parser = sub.add_parser("status")
    status_parser.add_argument("--tail", type=int, default=8)

    watch_parser = sub.add_parser("watch")
    watch_parser.add_argument("--tail", type=int, default=4)
    watch_parser.add_argument("--interval", type=float, default=3.0)

    stop_parser = sub.add_parser("stop")
    stop_parser.add_argument("--reason", default="manual_stop")

    sub.add_parser("data-health")
    report_parser = sub.add_parser("daily-report")
    report_parser.add_argument("--date", required=True)
    report_parser.add_argument("--timezone", default="Asia/Shanghai")
    sub.add_parser("self-test")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_standard_streams()
    args = build_parser().parse_args(argv)
    topology = load_topology(args.topology)
    try:
        if args.command == "inventory":
            print_json(build_inventory(topology, quick_check=args.quick_check))
            return 0
        if args.command == "preflight":
            result = preflight(
                topology,
                skipped=parse_targets(args.skip),
                quick_check=args.quick_check,
                require_runtime=not args.runtime_optional,
            )
            print_json(result)
            return 0 if result["ok"] else 2
        if args.command == "start":
            print_json(start_runtime(topology, adopt_running=args.adopt_running))
            return 0
        if args.command == "run":
            targets = configured_targets(topology, args.target)
            skipped = parse_targets(args.skip)
            result = run_guarded(
                topology,
                targets=targets,
                skipped=skipped,
                max_contacts=args.max_contacts,
                max_anomalies=args.max_anomalies,
                sleep_seconds=args.sleep,
            )
            print_json(result)
            return 0 if result.get("status") == "complete" else 3
        if args.command == "status":
            print_json(status_payload(topology, tail=args.tail))
            return 0
        if args.command == "watch":
            while True:
                print_json(status_payload(topology, tail=args.tail))
                time.sleep(max(args.interval, 1))
        if args.command == "stop":
            path = runtime_dir(topology) / "stop.requested"
            request_stop(path, reason=args.reason)
            print_json(
                {
                    "stopRequested": True,
                    "path": str(path),
                    "status": status_payload(topology),
                }
            )
            return 0
        if args.command == "data-health":
            print_json(data_health_payload(topology))
            return 0
        if args.command == "daily-report":
            print_json(
                daily_report_payload(
                    topology,
                    date_text=args.date,
                    timezone_name=args.timezone,
                )
            )
            return 0
        if args.command == "self-test":
            sample = classify_result(
                {"accepted": True, "processed": 1, "nextAction": "send_failed"}
            )
            print_json({"ok": sample.is_anomaly, "classification": asdict(sample)})
            return 0 if sample.is_anomaly else 1
    except KeyboardInterrupt:
        return 130
    except (ManagerError, ValueError) as error:
        print_json({"ok": False, "error": str(error)})
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
