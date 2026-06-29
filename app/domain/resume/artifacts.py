"""Persist downloaded resume artifacts and bridge them to parsed resumes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.db.engine import connect, run_migrations
from app.domain.resume.models import Resume
from app.domain.resume.name_parser import parse_resume_name
from app.domain.resume.repository import ResumeRepository


@dataclass(frozen=True)
class ResumeArtifact:
    """A resume file captured from a concrete platform conversation."""

    id: str
    session_id: str
    platform: str
    owner: str
    platform_conversation_id: str
    candidate_name_from_platform: str
    position: str
    file_path: str
    file_hash: str
    source_kind: str
    parse_status: str = "pending"
    parsed_name: str = ""
    resume_id: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""


class ResumeArtifactStore:
    """SQLite-backed store for resume files waiting to be parsed."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        run_migrations(self.database_path)

    def record_download(
        self,
        *,
        session_id: str,
        platform: str,
        owner: str,
        platform_conversation_id: str,
        candidate_name_from_platform: str,
        position: str,
        file_path: str | Path,
        file_hash: str,
        source_kind: str,
    ) -> ResumeArtifact:
        """Record a successfully downloaded file without parsing it."""

        now = _now_iso()
        artifact = ResumeArtifact(
            id=_artifact_id(session_id, file_hash),
            session_id=session_id,
            platform=platform,
            owner=owner,
            platform_conversation_id=platform_conversation_id,
            candidate_name_from_platform=candidate_name_from_platform,
            position=position,
            file_path=str(file_path),
            file_hash=file_hash,
            source_kind=source_kind,
            created_at=now,
            updated_at=now,
        )
        with connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO resume_artifacts (
                  id, session_id, platform, owner, platform_conversation_id,
                  candidate_name_from_platform, position, file_path, file_hash,
                  source_kind, parse_status, parsed_name, resume_id, error,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  platform_conversation_id = excluded.platform_conversation_id,
                  candidate_name_from_platform = excluded.candidate_name_from_platform,
                  position = excluded.position,
                  file_path = excluded.file_path,
                  source_kind = excluded.source_kind,
                  updated_at = excluded.updated_at
                """,
                _artifact_params(artifact),
            )
            connection.commit()
        return self.get(artifact.id) or artifact

    def get(self, artifact_id: str) -> ResumeArtifact | None:
        """Read one artifact by id."""

        with connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM resume_artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
        return _artifact_from_row(row) if row else None

    def list_pending(self, *, limit: int | None = None) -> list[ResumeArtifact]:
        """Return pending artifacts in creation order."""

        sql = "SELECT * FROM resume_artifacts WHERE parse_status = 'pending' ORDER BY created_at"
        params: tuple[Any, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        with connect(self.database_path) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [_artifact_from_row(row) for row in rows]

    def mark_parsed(self, artifact_id: str, *, resume_id: str, parsed_name: str) -> None:
        """Mark an artifact parsed and store the generated resume id."""

        now = _now_iso()
        with connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE resume_artifacts
                SET parse_status = 'parsed', parsed_name = ?, resume_id = ?,
                    error = '', updated_at = ?
                WHERE id = ?
                """,
                (parsed_name, resume_id, now, artifact_id),
            )
            connection.commit()

    def mark_failed(self, artifact_id: str, error: str) -> None:
        """Mark an artifact failed while preserving its platform link."""

        now = _now_iso()
        with connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE resume_artifacts
                SET parse_status = 'failed', error = ?, updated_at = ?
                WHERE id = ?
                """,
                (error[:1000], now, artifact_id),
            )
            connection.commit()


def parse_pending_artifacts(
    store: ResumeArtifactStore,
    resume_repository: ResumeRepository,
    *,
    conversation_repo: object | None = None,
    limit: int | None = None,
) -> list[ResumeArtifact]:
    """Parse pending artifacts and backfill resume bridge fields."""

    _ = conversation_repo
    parsed: list[ResumeArtifact] = []
    for artifact in store.list_pending(limit=limit):
        try:
            text = _read_resume_text(Path(artifact.file_path))
            parsed_name = parse_resume_name(text, file_name=artifact.file_path)
            resume_id = _resume_id(artifact)
            resume_repository.save(
                Resume(
                    id=resume_id,
                    name=parsed_name or None,
                    parsed_name=parsed_name,
                    applied_position=artifact.position or None,
                    job_type=artifact.position or None,
                    source_platform=artifact.platform,
                    source_owner=artifact.owner,
                    linked_session_id=artifact.session_id,
                    linked_platform=artifact.platform,
                    linked_owner=artifact.owner,
                    linked_platform_conversation_id=artifact.platform_conversation_id,
                    source_artifact_id=artifact.id,
                    updated_at=_now_iso(),
                    payload={
                        "name": parsed_name,
                        "rawText": text,
                        "platform": artifact.platform,
                        "owner": artifact.owner,
                        "candidateNameFromPlatform": artifact.candidate_name_from_platform,
                        "applied_position": artifact.position,
                        "sourceArtifactId": artifact.id,
                        "filePath": artifact.file_path,
                        "fileHash": artifact.file_hash,
                    },
                )
            )
            store.mark_parsed(artifact.id, resume_id=resume_id, parsed_name=parsed_name)
            current = store.get(artifact.id)
            if current is not None:
                parsed.append(current)
        except Exception as error:
            store.mark_failed(artifact.id, str(error))
    return parsed


def _artifact_id(session_id: str, file_hash: str) -> str:
    digest = hashlib.sha256(f"{session_id}|{file_hash}".encode()).hexdigest()
    return f"artifact_{digest[:24]}"


def _resume_id(artifact: ResumeArtifact) -> str:
    digest = hashlib.sha256(
        f"{artifact.session_id}|{artifact.file_hash}|resume".encode()
    ).hexdigest()
    return f"resume_{digest[:24]}"


def _read_resume_text(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(b"%PDF-"):
        extracted = _read_pdf_text(path)
        if extracted:
            return extracted
    for encoding in ("utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _read_pdf_text(path: Path) -> str:
    try:
        import fitz  # type: ignore[import-not-found]
    except Exception:
        return ""
    try:
        with fitz.open(path) as document:
            return "\n".join(page.get_text() for page in document)
    except Exception:
        return ""


def _artifact_params(artifact: ResumeArtifact) -> tuple[Any, ...]:
    return (
        artifact.id,
        artifact.session_id,
        artifact.platform,
        artifact.owner,
        artifact.platform_conversation_id,
        artifact.candidate_name_from_platform,
        artifact.position,
        artifact.file_path,
        artifact.file_hash,
        artifact.source_kind,
        artifact.parse_status,
        artifact.parsed_name,
        artifact.resume_id,
        artifact.error,
        artifact.created_at,
        artifact.updated_at,
    )


def _artifact_from_row(row: Any) -> ResumeArtifact:
    return ResumeArtifact(
        id=row["id"],
        session_id=row["session_id"],
        platform=row["platform"],
        owner=row["owner"],
        platform_conversation_id=row["platform_conversation_id"],
        candidate_name_from_platform=row["candidate_name_from_platform"],
        position=row["position"],
        file_path=row["file_path"],
        file_hash=row["file_hash"],
        source_kind=row["source_kind"],
        parse_status=row["parse_status"],
        parsed_name=row["parsed_name"],
        resume_id=row["resume_id"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
