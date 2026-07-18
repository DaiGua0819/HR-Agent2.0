from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from scripts import agent_manager


class AgentManagerTests(unittest.TestCase):
    def test_classifies_send_failure_as_anomaly(self) -> None:
        result = agent_manager.classify_result(
            {
                "accepted": True,
                "processed": 1,
                "nextAction": "send_failed",
                "stage": "direct_resume_prompt_send_failed",
                "decision": {
                    "action": "send_failed",
                    "reason": "direct_resume_prompt_send_failed",
                    "sendResult": {
                        "details": {"reason": "conversation_changed_before_send"}
                    },
                },
            }
        )

        self.assertTrue(result.is_anomaly)
        self.assertIn("send_failed", result.reasons)
        self.assertIn("conversation_changed_before_send", result.reasons)

    def test_accepts_successful_resume_result(self) -> None:
        result = agent_manager.classify_result(
            {
                "accepted": True,
                "processed": 1,
                "nextAction": "request_resume",
                "stage": "resume_attachment_downloaded",
                "decision": {"result": {"downloaded": True}},
            }
        )

        self.assertFalse(result.is_anomaly)
        self.assertEqual(result.reasons, [])

    def test_run_counters_include_processed_anomaly_contact(self) -> None:
        state = {"processed": 0, "anomalies": 0}
        classification = agent_manager.Classification(
            is_anomaly=True,
            reasons=["unknown_question"],
        )

        agent_manager.update_run_counters(
            state,
            {"processed": 1},
            classification,
        )

        self.assertEqual(state, {"processed": 1, "anomalies": 1})

    def test_boss_email_resume_handoff_is_not_an_anomaly(self) -> None:
        result = agent_manager.classify_result(
            {
                "platform": "boss",
                "accepted": True,
                "processed": 1,
                "nextAction": "request_resume",
                "stage": "direct_resume",
                "decision": {
                    "result": {
                        "resumeReceived": True,
                        "downloaded": False,
                        "reason": "boss_attachment_present_no_local_download",
                    }
                },
            }
        )

        self.assertFalse(result.is_anomaly)
        self.assertEqual(result.reasons, [])

    def test_boss_verified_request_is_reported_as_server_imap_handoff(self) -> None:
        payload = {
            "platform": "boss",
            "accepted": True,
            "processed": 1,
            "nextAction": "request_resume",
            "stage": "direct_resume",
            "decision": {
                "action": "request_resume",
                "reason": "direct_resume",
                "result": {
                    "ok": True,
                    "requested": True,
                    "confirmed": True,
                    "downloaded": False,
                },
            },
        }

        self.assertEqual(
            agent_manager.resume_handling(payload),
            "boss_request_verified_server_imap",
        )
        self.assertFalse(agent_manager.classify_result(payload).is_anomaly)

    def test_local_resume_download_is_reported_separately_from_boss(self) -> None:
        payload = {
            "platform": "zhilian",
            "accepted": True,
            "processed": 1,
            "nextAction": "request_resume",
            "stage": "resume_attachment_downloaded",
            "decision": {
                "result": {
                    "ok": True,
                    "downloaded": True,
                    "fileHash": "abc123",
                }
            },
        }

        self.assertEqual(agent_manager.resume_handling(payload), "local_resume_downloaded")

    def test_resume_request_waiting_is_not_reported_as_local_download(self) -> None:
        payload = {
            "platform": "zhilian",
            "accepted": True,
            "processed": 1,
            "nextAction": "request_resume",
            "stage": "direct_resume",
            "decision": {
                "result": {
                    "ok": True,
                    "requested": True,
                    "confirmed": True,
                    "downloaded": False,
                }
            },
        }

        self.assertEqual(agent_manager.resume_handling(payload), "resume_requested_waiting")

    def test_sanitizes_large_chat_text_but_keeps_identity_evidence(self) -> None:
        payload = {
            "decision": {
                "expected": {"name": "目标候选人"},
                "actual": {"name": "右侧候选人"},
                "result": {
                    "state": {"summary": "x" * 5000},
                    "rawText": "y" * 5000,
                    "bytes": b"pdf",
                },
            }
        }

        sanitized = agent_manager.sanitize_payload(payload)

        self.assertEqual(sanitized["decision"]["expected"]["name"], "目标候选人")
        self.assertEqual(sanitized["decision"]["actual"]["name"], "右侧候选人")
        self.assertEqual(
            sanitized["decision"]["result"]["state"]["summary"],
            {"omitted": True, "length": 5000},
        )
        self.assertEqual(
            sanitized["decision"]["result"]["rawText"],
            {"omitted": True, "length": 5000},
        )
        self.assertEqual(
            sanitized["decision"]["result"]["bytes"],
            {"type": "bytes", "length": 3},
        )

    def test_parses_owner_platform_targets(self) -> None:
        self.assertEqual(
            agent_manager.parse_target("和新红:boss"),
            ("和新红", "boss"),
        )
        with self.assertRaises(ValueError):
            agent_manager.parse_target("和新红")

    def test_stop_flag_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stop.requested"

            agent_manager.request_stop(path, reason="manual_test")

            self.assertTrue(agent_manager.stop_requested(path))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["reason"], "manual_test")
            agent_manager.clear_stop(path)
            self.assertFalse(path.exists())

    def test_run_guarded_processes_distinct_owners_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_root = Path(directory) / "agent-manager"
            topology = {
                "controlPlane": {"port": 18081},
                "owners": [
                    {"owner": "和新红"},
                    {"owner": "宋峰峰"},
                ],
            }
            arrivals = {
                "和新红": threading.Event(),
                "宋峰峰": threading.Event(),
            }
            overlaps: dict[str, bool] = {}
            call_counts = {"和新红": 0, "宋峰峰": 0}
            count_lock = threading.Lock()

            def fake_http_json(url: str, *, method: str, timeout: float) -> dict[str, object]:
                del method, timeout
                owner = parse_qs(urlparse(url).query)["owner"][0]
                with count_lock:
                    call_counts[owner] += 1
                    call_number = call_counts[owner]
                if call_number > 1:
                    return {"accepted": True, "processed": 0}
                other = "宋峰峰" if owner == "和新红" else "和新红"
                arrivals[owner].set()
                overlaps[owner] = arrivals[other].wait(timeout=0.5)
                return {"accepted": True, "processed": 1}

            with (
                patch.object(agent_manager, "preflight", return_value={"ok": True}),
                patch.object(agent_manager, "runtime_dir", return_value=runtime_root),
                patch.object(agent_manager, "cdp_inventory", return_value={"blockers": []}),
                patch.object(agent_manager, "worker_status", return_value={"agentBusy": False}),
                patch.object(agent_manager, "http_json", side_effect=fake_http_json),
            ):
                result = agent_manager.run_guarded(
                    topology,
                    targets=[("和新红", "boss"), ("宋峰峰", "boss")],
                    skipped=set(),
                    max_contacts=0,
                    max_anomalies=0,
                    sleep_seconds=0,
                )

            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["processed"], 2)
            self.assertEqual(overlaps, {"和新红": True, "宋峰峰": True})
            self.assertEqual(call_counts, {"和新红": 2, "宋峰峰": 2})

    def test_targets_by_owner_preserves_each_owners_platform_order(self) -> None:
        self.assertEqual(
            agent_manager.targets_by_owner(
                [
                    ("和新红", "boss"),
                    ("宋峰峰", "boss"),
                    ("和新红", "job51"),
                    ("宋峰峰", "zhilian"),
                    ("和新红", "zhilian"),
                ]
            ),
            [
                ("和新红", ["boss", "job51", "zhilian"]),
                ("宋峰峰", ["boss", "zhilian"]),
            ],
        )

    def test_guarded_run_skips_tolerated_contact_anomaly_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_root = Path(directory) / "agent-manager"
            topology = {
                "controlPlane": {"port": 18081},
                "owners": [{"owner": "owner"}],
            }
            exclusions_by_call: list[list[str]] = []

            def fake_http_json(
                url: str, *, method: str, timeout: float
            ) -> dict[str, object]:
                del method, timeout
                query = parse_qs(urlparse(url).query)
                exclusions_by_call.append(query.get("exclude_conversation_id", []))
                call_number = len(exclusions_by_call)
                if call_number == 1:
                    return {
                        "accepted": True,
                        "processed": 1,
                        "conversationId": "candidate-detail-a",
                        "selectedConversationId": "row-a",
                        "nextAction": "request_resume_failed",
                        "stage": "request_resume_action_failed",
                    }
                if call_number == 2:
                    return {
                        "accepted": True,
                        "processed": 1,
                        "conversationId": "candidate-b",
                        "selectedConversationId": "row-b",
                        "nextAction": "request_resume",
                        "stage": "resume_attachment_downloaded",
                        "decision": {"result": {"downloaded": True}},
                    }
                return {"accepted": True, "processed": 0}

            with (
                patch.object(agent_manager, "preflight", return_value={"ok": True}),
                patch.object(agent_manager, "runtime_dir", return_value=runtime_root),
                patch.object(agent_manager, "cdp_inventory", return_value={"blockers": []}),
                patch.object(agent_manager, "worker_status", return_value={"agentBusy": False}),
                patch.object(agent_manager, "http_json", side_effect=fake_http_json),
            ):
                result = agent_manager.run_guarded(
                    topology,
                    targets=[("owner", "job51")],
                    skipped=set(),
                    max_contacts=10,
                    max_anomalies=4,
                    sleep_seconds=0,
                )

            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["processed"], 2)
            self.assertEqual(result["anomalies"], 1)
            self.assertEqual(exclusions_by_call, [[], ["row-a"], ["row-a"]])

    def test_guarded_run_stops_on_fifth_contact_anomaly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_root = Path(directory) / "agent-manager"
            topology = {
                "controlPlane": {"port": 18081},
                "owners": [{"owner": "owner"}],
            }
            call_count = 0

            def fake_http_json(
                url: str, *, method: str, timeout: float
            ) -> dict[str, object]:
                nonlocal call_count
                del method, timeout
                query = parse_qs(urlparse(url).query)
                self.assertEqual(
                    len(query.get("exclude_conversation_id", [])),
                    call_count,
                )
                call_count += 1
                return {
                    "accepted": True,
                    "processed": 1,
                    "conversationId": f"candidate-{call_count}",
                    "selectedConversationId": f"row-{call_count}",
                    "nextAction": "request_resume_failed",
                    "stage": "request_resume_action_failed",
                }

            with (
                patch.object(agent_manager, "preflight", return_value={"ok": True}),
                patch.object(agent_manager, "runtime_dir", return_value=runtime_root),
                patch.object(agent_manager, "cdp_inventory", return_value={"blockers": []}),
                patch.object(agent_manager, "worker_status", return_value={"agentBusy": False}),
                patch.object(agent_manager, "http_json", side_effect=fake_http_json),
            ):
                result = agent_manager.run_guarded(
                    topology,
                    targets=[("owner", "job51")],
                    skipped=set(),
                    max_contacts=10,
                    max_anomalies=4,
                    sleep_seconds=0,
                )

            self.assertEqual(result["status"], "stopped_on_anomaly")
            self.assertEqual(result["processed"], 5)
            self.assertEqual(result["anomalies"], 5)
            self.assertEqual(call_count, 5)

    def test_owner_lanes_finish_current_contact_after_global_anomaly_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_root = Path(directory) / "agent-manager"
            topology = {
                "controlPlane": {"port": 18081},
                "owners": [
                    {"owner": "和新红"},
                    {"owner": "宋峰峰"},
                ],
            }
            first_calls_ready = threading.Barrier(2)
            call_counts = {"和新红": 0, "宋峰峰": 0}
            count_lock = threading.Lock()

            def fake_http_json(url: str, *, method: str, timeout: float) -> dict[str, object]:
                del method, timeout
                owner = parse_qs(urlparse(url).query)["owner"][0]
                with count_lock:
                    call_counts[owner] += 1
                first_calls_ready.wait(timeout=1)
                if owner == "和新红":
                    return {
                        "accepted": True,
                        "processed": 1,
                        "nextAction": "send_failed",
                        "stage": "send_failed",
                    }

                current_path = runtime_root / "current_run.json"
                for _ in range(100):
                    current = json.loads(current_path.read_text(encoding="utf-8"))
                    if current.get("status") == "stopped_on_anomaly":
                        break
                    threading.Event().wait(0.01)
                return {"accepted": True, "processed": 1}

            with (
                patch.object(agent_manager, "preflight", return_value={"ok": True}),
                patch.object(agent_manager, "runtime_dir", return_value=runtime_root),
                patch.object(agent_manager, "cdp_inventory", return_value={"blockers": []}),
                patch.object(agent_manager, "worker_status", return_value={"agentBusy": False}),
                patch.object(agent_manager, "http_json", side_effect=fake_http_json),
            ):
                result = agent_manager.run_guarded(
                    topology,
                    targets=[("和新红", "boss"), ("宋峰峰", "boss")],
                    skipped=set(),
                    max_contacts=0,
                    max_anomalies=0,
                    sleep_seconds=0,
                )

            self.assertEqual(result["status"], "stopped_on_anomaly")
            self.assertEqual(result["processed"], 2)
            self.assertEqual(result["anomalies"], 1)
            self.assertEqual(call_counts, {"和新红": 1, "宋峰峰": 1})

    def test_anomaly_stop_blocks_contact_not_yet_dispatched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_root = Path(directory) / "agent-manager"
            topology = {
                "controlPlane": {"port": 18081},
                "owners": [
                    {"owner": "和新红"},
                    {"owner": "宋峰峰"},
                ],
            }
            dispatched: list[str] = []

            def fake_cdp_inventory(owner_config: dict[str, object]) -> dict[str, object]:
                if owner_config["owner"] == "和新红":
                    return {
                        "blockers": [
                            {"platform": "boss", "reason": "login_required"}
                        ]
                    }
                return {"blockers": []}

            def fake_worker_status(owner_config: dict[str, object]) -> dict[str, object]:
                if owner_config["owner"] == "宋峰峰":
                    current_path = runtime_root / "current_run.json"
                    for _ in range(100):
                        current = json.loads(current_path.read_text(encoding="utf-8"))
                        if current.get("status") == "stopped_on_anomaly":
                            break
                        threading.Event().wait(0.01)
                return {"agentBusy": False}

            def fake_http_json(url: str, *, method: str, timeout: float) -> dict[str, object]:
                del method, timeout
                dispatched.append(parse_qs(urlparse(url).query)["owner"][0])
                return {"accepted": True, "processed": 0}

            with (
                patch.object(agent_manager, "preflight", return_value={"ok": True}),
                patch.object(agent_manager, "runtime_dir", return_value=runtime_root),
                patch.object(agent_manager, "cdp_inventory", side_effect=fake_cdp_inventory),
                patch.object(agent_manager, "worker_status", side_effect=fake_worker_status),
                patch.object(agent_manager, "http_json", side_effect=fake_http_json),
            ):
                result = agent_manager.run_guarded(
                    topology,
                    targets=[("和新红", "boss"), ("宋峰峰", "boss")],
                    skipped=set(),
                    max_contacts=0,
                    max_anomalies=0,
                    sleep_seconds=0,
                )

            self.assertEqual(result["status"], "stopped_on_anomaly")
            self.assertEqual(dispatched, [])

    def test_pause_request_blocks_contact_not_yet_dispatched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_root = Path(directory) / "agent-manager"
            topology = {
                "controlPlane": {"port": 18081},
                "owners": [{"owner": "和新红"}],
            }
            dispatched: list[str] = []

            def fake_worker_status(owner_config: dict[str, object]) -> dict[str, object]:
                del owner_config
                agent_manager.request_stop(
                    runtime_root / "stop.requested",
                    reason="test_pause_window",
                )
                return {"agentBusy": False}

            def fake_http_json(url: str, *, method: str, timeout: float) -> dict[str, object]:
                del method, timeout
                dispatched.append(url)
                return {"accepted": True, "processed": 0}

            with (
                patch.object(agent_manager, "preflight", return_value={"ok": True}),
                patch.object(agent_manager, "runtime_dir", return_value=runtime_root),
                patch.object(agent_manager, "cdp_inventory", return_value={"blockers": []}),
                patch.object(agent_manager, "worker_status", side_effect=fake_worker_status),
                patch.object(agent_manager, "http_json", side_effect=fake_http_json),
            ):
                result = agent_manager.run_guarded(
                    topology,
                    targets=[("和新红", "boss")],
                    skipped=set(),
                    max_contacts=0,
                    max_anomalies=0,
                    sleep_seconds=0,
                )

            self.assertEqual(result["status"], "stop_requested")
            self.assertEqual(dispatched, [])

    def test_run_guarded_rejects_an_existing_process_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_root = Path(directory) / "agent-manager"
            runtime_root.mkdir(parents=True)
            topology = {
                "controlPlane": {"port": 18081},
                "owners": [{"owner": "和新红"}],
            }

            with agent_manager.AgentManagerRunLock(runtime_root / "run.lock"):
                with patch.object(agent_manager, "runtime_dir", return_value=runtime_root):
                    with self.assertRaisesRegex(
                        agent_manager.ManagerError,
                        "run_already_active",
                    ):
                        agent_manager.run_guarded(
                            topology,
                            targets=[("和新红", "boss")],
                            skipped=set(),
                            max_contacts=0,
                            max_anomalies=0,
                            sleep_seconds=0,
                        )

    def test_run_guarded_marks_state_failed_when_an_owner_lane_crashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_root = Path(directory) / "agent-manager"
            topology = {
                "controlPlane": {"port": 18081},
                "owners": [{"owner": "和新红"}],
            }

            with (
                patch.object(agent_manager, "preflight", return_value={"ok": True}),
                patch.object(agent_manager, "runtime_dir", return_value=runtime_root),
                patch.object(
                    agent_manager,
                    "cdp_inventory",
                    side_effect=RuntimeError("inventory_crashed"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "inventory_crashed"):
                    agent_manager.run_guarded(
                        topology,
                        targets=[("和新红", "boss")],
                        skipped=set(),
                        max_contacts=0,
                        max_anomalies=0,
                        sleep_seconds=0,
                    )

            current = json.loads(
                (runtime_root / "current_run.json").read_text(encoding="utf-8")
            )
            self.assertEqual(current["status"], "failed")
            self.assertEqual(current["error"], "inventory_crashed")

    def test_boss_security_query_on_chat_page_is_not_a_blocker(self) -> None:
        page = {
            "title": "BOSS直聘",
            "url": "https://www.zhipin.com/web/chat/index?_security_check=1_123",
        }

        self.assertIsNone(agent_manager.page_blocker("boss", page))
        self.assertEqual(
            agent_manager.page_blocker(
                "boss",
                {
                    "title": "安全验证",
                    "url": "https://www.zhipin.com/web/user/verify.html",
                },
            )["reason"],
            "security_verification_required",
        )

    def test_browser_command_uses_configured_cloak_profile_and_cdp(self) -> None:
        command = agent_manager.browser_command(
            {"browserExecutable": r"C:\CloakBrowser\chrome.exe"},
            {
                "profileDir": r"C:\Recruit\profiles\hexinhong",
                "cdpPort": 9222,
            },
        )

        self.assertEqual(command[0], r"C:\CloakBrowser\chrome.exe")
        self.assertIn("--remote-debugging-port=9222", command)
        self.assertIn(r"--user-data-dir=C:\Recruit\profiles\hexinhong", command)
        self.assertIn("--remote-allow-origins=*", command)

    def test_subprocess_environment_forces_utf8_on_windows(self) -> None:
        environment = agent_manager.subprocess_environment({"EXISTING": "value"})

        self.assertEqual(environment["EXISTING"], "value")
        self.assertEqual(environment["PYTHONUTF8"], "1")
        self.assertEqual(environment["PYTHONIOENCODING"], "utf-8")

    def test_data_health_reports_local_pipeline_without_treating_boss_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "data" / "resumes.sqlite"
            database.parent.mkdir(parents=True)
            connection = sqlite3.connect(database)
            try:
                connection.executescript(
                    """
                    CREATE TABLE conversation_sessions (
                        id TEXT PRIMARY KEY,
                        platform TEXT,
                        position TEXT,
                        applied_position TEXT,
                        updated_at TEXT
                    );
                    CREATE TABLE conversation_messages (
                        id TEXT PRIMARY KEY,
                        created_at TEXT
                    );
                    CREATE TABLE resume_artifacts (
                        id TEXT PRIMARY KEY,
                        session_id TEXT,
                        platform TEXT,
                        position TEXT,
                        file_hash TEXT,
                        parse_status TEXT,
                        created_at TEXT
                    );
                    CREATE TABLE resumes (
                        id TEXT PRIMARY KEY,
                        updated_at TEXT
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO conversation_sessions VALUES (?, ?, ?, ?, ?)",
                    ("s1", "job51", "运营B", "运营B", "2026-07-16T00:00:00+00:00"),
                )
                connection.execute(
                    "INSERT INTO conversation_messages VALUES (?, ?)",
                    ("m1", "2026-07-16T00:01:00+00:00"),
                )
                connection.executemany(
                    "INSERT INTO resume_artifacts VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            "a1",
                            "s1",
                            "job51",
                            "运营B",
                            "hash-1",
                            "parsed",
                            "2026-07-16T00:02:00+00:00",
                        ),
                        (
                            "a2",
                            "s1",
                            "job51",
                            "运营B",
                            "hash-2",
                            "pending",
                            "2026-07-16T00:03:00+00:00",
                        ),
                        (
                            "a3",
                            "s1",
                            "job51",
                            "运营B",
                            "hash-2",
                            "pending",
                            "2026-07-16T00:04:00+00:00",
                        ),
                        (
                            "a4",
                            "s1",
                            "boss",
                            "运营B",
                            "boss-hash",
                            "pending",
                            "2026-07-16T00:04:30+00:00",
                        ),
                    ],
                )
                connection.execute(
                    "INSERT INTO resumes VALUES (?, ?)",
                    ("r1", "2026-07-16T00:05:00+00:00"),
                )
                connection.commit()
            finally:
                connection.close()
            sync_dir = root / "data" / "sync"
            sync_dir.mkdir(parents=True)
            (sync_dir / "auto_sync_state.json").write_text(
                json.dumps(
                    {
                        "lastSuccessAt": "2026-07-16T00:06:00+00:00",
                        "lastError": "",
                        "consecutiveFailures": 0,
                    }
                ),
                encoding="utf-8",
            )

            health = agent_manager.data_health_payload(
                {"projectRoot": str(root), "databasePath": str(database)}
            )

            self.assertEqual(health["localResumePipeline"]["artifacts"]["total"], 3)
            self.assertEqual(health["localResumePipeline"]["artifacts"]["uniqueFiles"], 2)
            self.assertEqual(health["localResumePipeline"]["artifacts"]["byStatus"]["pending"], 2)
            self.assertEqual(
                health["localResumePipeline"]["pendingByPlatformJob"],
                [{"platform": "job51", "job": "运营B", "count": 2}],
            )
            self.assertEqual(
                health["bossContract"]["completion"],
                "verified_request_is_successful_resume_acquisition",
            )
            self.assertFalse(health["bossContract"]["localFileRequired"])
            self.assertEqual(health["autoSync"]["consecutiveFailures"], 0)

    def test_parser_exposes_data_health_command(self) -> None:
        args = agent_manager.build_parser().parse_args(["data-health"])

        self.assertEqual(args.command, "data-health")

    def test_data_health_canonicalizes_common_job_aliases(self) -> None:
        self.assertEqual(agent_manager.canonical_job_label("AI 产品经理"), "AI产品经理")
        self.assertEqual(agent_manager.canonical_job_label("AI+产品经理"), "AI产品经理")
        self.assertEqual(agent_manager.canonical_job_label("B端社交媒体运营"), "运营B")
        self.assertEqual(
            agent_manager.canonical_job_label("企业内容运营负责人（B2B/短视频方向）"),
            "运营A",
        )

    def test_daily_report_combines_boss_handoffs_and_local_unique_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "data" / "resumes.sqlite"
            database.parent.mkdir(parents=True)
            connection = sqlite3.connect(database)
            try:
                connection.executescript(
                    """
                    CREATE TABLE conversation_sessions (
                        id TEXT PRIMARY KEY,
                        platform TEXT,
                        owner TEXT,
                        candidate_name TEXT,
                        position TEXT,
                        applied_position TEXT,
                        platform_conversation_id TEXT,
                        last_seen_at TEXT,
                        updated_at TEXT
                    );
                    CREATE TABLE resume_artifacts (
                        id TEXT PRIMARY KEY,
                        session_id TEXT,
                        platform TEXT,
                        position TEXT,
                        file_hash TEXT,
                        created_at TEXT
                    );
                    """
                )
                connection.executemany(
                    "INSERT INTO conversation_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            "boss-session",
                            "boss",
                            "宋峰峰",
                            "张三",
                            "AI产品经理",
                            "AI产品经理",
                            "boss-conversation",
                            "2026-07-15T01:00:05+00:00",
                            "2026-07-15T01:00:05+00:00",
                        ),
                        (
                            "zhilian-session",
                            "zhilian",
                            "和新红",
                            "李四",
                            "B端社交媒体运营",
                            "B端社交媒体运营",
                            "zhilian-conversation",
                            "2026-07-15T02:00:05+00:00",
                            "2026-07-15T02:00:05+00:00",
                        ),
                    ],
                )
                connection.execute(
                    "INSERT INTO resume_artifacts VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "artifact-1",
                        "zhilian-session",
                        "zhilian",
                        "B端社交媒体运营",
                        "hash-1",
                        "2026-07-15T02:00:04+00:00",
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            run_dir = root / "data" / "agent_manager" / "runs"
            run_dir.mkdir(parents=True)
            events = [
                {
                    "timestamp": "2026-07-15T01:00:06+00:00",
                    "event": "contact_result",
                    "owner": "宋峰峰",
                    "platform": "boss",
                    "classification": {"is_anomaly": False, "reasons": []},
                    "summary": {"processed": 1, "conversationId": "boss-conversation"},
                    "response": {
                        "platform": "boss",
                        "processed": 1,
                        "nextAction": "request_resume",
                        "decision": {
                            "action": "request_resume",
                            "result": {"ok": True, "requested": True, "confirmed": True},
                        },
                    },
                },
                {
                    "timestamp": "2026-07-15T02:00:06+00:00",
                    "event": "contact_result",
                    "owner": "和新红",
                    "platform": "zhilian",
                    "classification": {"is_anomaly": False, "reasons": []},
                    "summary": {"processed": 1, "conversationId": "zhilian-conversation"},
                    "response": {
                        "platform": "zhilian",
                        "processed": 1,
                        "nextAction": "request_resume",
                        "decision": {
                            "action": "request_resume",
                            "result": {"ok": True, "downloaded": True, "fileHash": "hash-1"},
                        },
                    },
                },
            ]
            (run_dir / "sample.jsonl").write_text(
                "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
                encoding="utf-8",
            )

            report = agent_manager.daily_report_payload(
                {"projectRoot": str(root), "databasePath": str(database)},
                date_text="2026-07-15",
            )

            self.assertEqual(report["totals"]["processedContacts"], 2)
            self.assertEqual(report["totals"]["bossHandoffs"], 1)
            self.assertEqual(report["totals"]["localUniqueFiles"], 1)
            self.assertEqual(report["totals"]["businessResumeAcquisitions"], 2)
            self.assertEqual(
                report["byJobPlatform"],
                [
                    {
                        "job": "AI产品经理",
                        "platform": "boss",
                        "processedContacts": 1,
                        "bossHandoffs": 1,
                        "localUniqueFiles": 0,
                        "businessResumeAcquisitions": 1,
                        "resumeRequestsWaiting": 0,
                        "anomalies": 0,
                    },
                    {
                        "job": "运营B",
                        "platform": "zhilian",
                        "processedContacts": 1,
                        "bossHandoffs": 0,
                        "localUniqueFiles": 1,
                        "businessResumeAcquisitions": 1,
                        "resumeRequestsWaiting": 0,
                        "anomalies": 0,
                    },
                ],
            )

    def test_parser_exposes_daily_report_command(self) -> None:
        args = agent_manager.build_parser().parse_args(
            ["daily-report", "--date", "2026-07-15"]
        )

        self.assertEqual(args.command, "daily-report")
        self.assertEqual(args.date, "2026-07-15")

if __name__ == "__main__":
    unittest.main()
