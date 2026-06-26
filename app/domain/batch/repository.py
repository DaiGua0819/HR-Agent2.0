"""批量任务 SQLite repository。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.db.engine import connect, run_migrations
from app.domain.batch.models import BatchItem, BatchJob, now_iso
from app.settings import load_settings


class BatchRepository:
    """批量任务持久化存储。"""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = (
            Path(database_path)
            if database_path
            else load_settings().resolved_database_path
        )
        run_migrations(self.database_path)

    def save(self, job: BatchJob) -> BatchJob:
        """保存任务与明细。"""

        job.updated_at = now_iso()
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO batch_jobs (id, parse_mode, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  parse_mode = excluded.parse_mode,
                  status = excluded.status,
                  updated_at = excluded.updated_at
                """,
                (job.id, job.parse_mode, job.status, job.created_at, job.updated_at),
            )
            for item in job.items:
                item.updated_at = now_iso()
                connection.execute(
                    """
                    INSERT INTO batch_items (
                      id, job_id, filename, file_path, status, message, resume_id,
                      payload, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      filename = excluded.filename,
                      file_path = excluded.file_path,
                      status = excluded.status,
                      message = excluded.message,
                      resume_id = excluded.resume_id,
                      payload = excluded.payload,
                      updated_at = excluded.updated_at
                    """,
                    _item_params(item),
                )
            connection.commit()
        return job

    def get(self, job_id: str) -> BatchJob | None:
        """读取任务。"""

        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM batch_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            items = connection.execute(
                "SELECT * FROM batch_items WHERE job_id = ? ORDER BY created_at",
                (job_id,),
            ).fetchall()
        return _job_from_row(row, [_item_from_row(item) for item in items])

    def list(self) -> list[BatchJob]:
        """列出任务。"""

        with connect(self.database_path) as connection:
            rows = connection.execute(
                "SELECT * FROM batch_jobs ORDER BY updated_at DESC"
            ).fetchall()
        jobs: list[BatchJob] = []
        for row in rows:
            job = self.get(row["id"])
            if job is not None:
                jobs.append(job)
        return jobs

    def clear(self) -> None:
        """清空任务；仅用于临时库测试。"""

        with connect(self.database_path) as connection:
            connection.execute("DELETE FROM batch_items")
            connection.execute("DELETE FROM batch_jobs")
            connection.commit()


GLOBAL_BATCH_REPOSITORY = BatchRepository()
InMemoryBatchRepository = BatchRepository


def get_batch_job(job_id: str) -> dict[str, object] | None:
    """读取批量任务。"""

    job = GLOBAL_BATCH_REPOSITORY.get(job_id)
    return job.to_dict() if job else None


def _item_params(item: BatchItem) -> tuple[Any, ...]:
    return (
        item.id,
        item.job_id,
        item.file_name,
        item.file_path,
        item.status,
        item.error,
        item.resume_id,
        json.dumps(item.payload, ensure_ascii=False, sort_keys=True),
        item.created_at,
        item.updated_at,
    )


def _job_from_row(row: Any, items: list[BatchItem]) -> BatchJob:
    return BatchJob(
        id=row["id"],
        parse_mode=row["parse_mode"],
        status=row["status"],
        items=items,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _item_from_row(row: Any) -> BatchItem:
    return BatchItem(
        id=row["id"],
        job_id=row["job_id"],
        file_name=row["filename"],
        file_path=row["file_path"],
        status=row["status"],
        payload=json.loads(row["payload"]),
        error=row["message"] or "",
        resume_id=row["resume_id"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
