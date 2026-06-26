"""一次性烟测：读取旧 resumes.sqlite 的条数和前几条索引列。"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.domain.resume.repository import ResumeRepository
from app.settings import load_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读验证旧 resumes.sqlite")
    parser.add_argument("--db", type=Path, default=None, help="旧 SQLite 路径；为空则读配置")
    parser.add_argument("--limit", type=int, default=5, help="打印样例条数")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    db_path = args.db or settings.resolved_legacy_resume_db_path
    repository = ResumeRepository(db_path, read_only=True)
    print(f"database={db_path}")
    print(f"count={repository.count()}")
    for record in repository.list_resumes(limit=args.limit):
        print(
            {
                "id": record.id,
                "name": record.candidate_name,
                "phone_key": record.phone_key,
                "job_type": record.job_type,
                "match_score": record.match_score,
                "updated_at": record.updated_at,
            }
        )


if __name__ == "__main__":
    main()
