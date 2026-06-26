"""Run one 51job unread-message pass; dry-run by default."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    """Run one 51job processing pass."""

    from app.core.constants import Platform

    from platform_once_common import run

    run(Platform.JOB51)


if __name__ == "__main__":
    main()
