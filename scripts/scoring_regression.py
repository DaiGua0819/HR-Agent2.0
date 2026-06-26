"""打分回归校验脚本。

用法：
  python scripts/scoring_regression.py --database data/resumes_copy.sqlite --output scores.json
  python scripts/scoring_regression.py --database data/resumes_copy.sqlite --baseline old_scores.csv

脚本只读传入的数据库副本，不写库。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from app.domain.resume.models import Resume
from app.domain.resume.repository import ResumeRepository
from app.domain.scoring.service import ScoringService


def main() -> None:
    """命令行入口。"""

    args = _parse_args()
    rows = run_regression(args.database)
    if args.baseline:
        diffs = compare_baseline(rows, args.baseline)
        print(
            json.dumps(
                {"count": len(rows), "diffCount": len(diffs), "diffs": diffs},
                ensure_ascii=False,
            )
        )
    else:
        print(json.dumps({"count": len(rows)}, ensure_ascii=False))
    if args.output:
        write_output(rows, args.output)


def run_regression(database_path: str | Path) -> list[dict[str, Any]]:
    """对数据库副本逐条跑新评分。"""

    repository = ResumeRepository(database_path, read_only=True)
    service = ScoringService(repository)
    rows: list[dict[str, Any]] = []
    for record in repository.iter_resumes():
        result = service.score_resume(Resume.from_record(record))
        rows.append(
            {
                "resumeId": record.id,
                "jobType": result.get("jobType") or "",
                "score": result["score"],
                "level": result["level"],
                "version": result["version"],
            }
        )
    return rows


def compare_baseline(rows: list[dict[str, Any]], baseline_path: str | Path) -> list[dict[str, Any]]:
    """与旧系统基线 CSV/JSON 比对。"""

    baseline = _read_baseline(baseline_path)
    diffs: list[dict[str, Any]] = []
    for row in rows:
        old = baseline.get(str(row["resumeId"]))
        if old is None:
            diffs.append({"resumeId": row["resumeId"], "reason": "missing_in_baseline"})
            continue
        if int(old.get("score", -1)) != int(row["score"]) or old.get("level") != row["level"]:
            diffs.append({"resumeId": row["resumeId"], "old": old, "new": row})
    return diffs


def write_output(rows: list[dict[str, Any]], output_path: str | Path) -> None:
    """按扩展名写 JSON 或 CSV。"""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=["resumeId", "jobType", "score", "level", "version"],
            )
            writer.writeheader()
            writer.writerows(rows)
        return
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_baseline(path: str | Path) -> dict[str, dict[str, Any]]:
    source = Path(path)
    if source.suffix.lower() == ".csv":
        with source.open("r", newline="", encoding="utf-8") as file:
            return {str(row["resumeId"]): dict(row) for row in csv.DictReader(file)}
    data = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {str(row["resumeId"]): dict(row) for row in data}
    if isinstance(data, dict):
        return {str(key): dict(value) for key, value in data.items()}
    raise ValueError("unsupported_baseline_format")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run scoring regression on a SQLite copy.")
    parser.add_argument("--database", required=True, help="SQLite database copy path.")
    parser.add_argument("--output", help="Write scores to .json or .csv.")
    parser.add_argument("--baseline", help="Old system baseline .json or .csv.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
