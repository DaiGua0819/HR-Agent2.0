"""Run the encrypted local-to-preview automatic synchronization worker."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.domain.auto_sync.locking import SingleInstanceLock  # noqa: E402
from app.domain.auto_sync.worker import AutoSyncWorker, AutoSyncWorkerConfig  # noqa: E402
from app.settings import load_settings  # noqa: E402


def build_worker() -> AutoSyncWorker:
    settings = load_settings()
    if not settings.auto_sync_server_url:
        raise RuntimeError("AUTO_SYNC_SERVER_URL is required")
    if len(settings.auto_sync_secret) < 32:
        raise RuntimeError("AUTO_SYNC_SECRET must contain at least 32 characters")
    return AutoSyncWorker(
        AutoSyncWorkerConfig(
            database_path=settings.resolved_database_path,
            server_url=settings.auto_sync_server_url,
            secret=settings.auto_sync_secret,
            state_path=settings.resolved_auto_sync_state_path,
            pending_dir=settings.resolved_auto_sync_pending_dir,
            source=settings.auto_sync_source,
            interval_seconds=settings.auto_sync_interval_seconds,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--bootstrap-current", action="store_true")
    args = parser.parse_args()
    worker = build_worker()
    lock_path = worker.config.state_path.with_suffix(".lock")
    with SingleInstanceLock(lock_path):
        if args.bootstrap_current:
            print(json.dumps(worker.bootstrap_current(), ensure_ascii=False, indent=2))
            return
        if args.once:
            print(json.dumps(worker.run_once(), ensure_ascii=False, indent=2))
            return
        worker.run_forever()


if __name__ == "__main__":
    main()
