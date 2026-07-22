"""Persist downloaded resume artifacts and bridge them to parsed resumes."""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from app.db.engine import connect, run_migrations
from app.domain.resume.job_types import canonical_resume_job_type
from app.domain.resume.models import Resume
from app.domain.resume.name_parser import choose_resume_name, parse_resume_name
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
        normalized_position = canonical_resume_job_type(position) or str(position or "").strip()
        artifact = ResumeArtifact(
            id=_artifact_id(session_id, file_hash),
            session_id=session_id,
            platform=platform,
            owner=owner,
            platform_conversation_id=platform_conversation_id,
            candidate_name_from_platform=candidate_name_from_platform,
            position=normalized_position,
            file_path=str(file_path),
            file_hash=file_hash,
            source_kind=source_kind,
            created_at=now,
            updated_at=now,
        )
        with connect(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_row = _find_business_download_row(
                connection,
                session_id=session_id,
                platform=platform,
                owner=owner,
                platform_conversation_id=platform_conversation_id,
                position=normalized_position,
            )
            if existing_row is not None:
                existing = _artifact_from_row(existing_row)
                if existing.parse_status == "parsed":
                    return existing
                connection.execute(
                    """
                    UPDATE resume_artifacts
                    SET platform_conversation_id = ?, candidate_name_from_platform = ?,
                        position = ?, file_path = ?, file_hash = ?, source_kind = ?,
                        parse_status = 'pending', parsed_name = '', resume_id = '',
                        error = '', updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        platform_conversation_id,
                        candidate_name_from_platform,
                        normalized_position,
                        str(file_path),
                        file_hash,
                        source_kind,
                        now,
                        existing.id,
                    ),
                )
                connection.commit()
                refreshed = connection.execute(
                    "SELECT * FROM resume_artifacts WHERE id = ?",
                    (existing.id,),
                ).fetchone()
                return _artifact_from_row(refreshed)
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

    def has_business_download(
        self,
        *,
        session_id: str,
        platform: str,
        owner: str,
        platform_conversation_id: str,
        position: str,
    ) -> bool:
        """Return whether this candidate/job already has a captured resume file."""

        return (
            self.find_business_download(
                session_id=session_id,
                platform=platform,
                owner=owner,
                platform_conversation_id=platform_conversation_id,
                position=position,
            )
            is not None
        )

    def find_business_download(
        self,
        *,
        session_id: str,
        platform: str,
        owner: str,
        platform_conversation_id: str,
        position: str,
    ) -> ResumeArtifact | None:
        """Find an existing artifact by canonical session or stable platform identity."""

        with connect(self.database_path) as connection:
            row = _find_business_download_row(
                connection,
                session_id=session_id,
                platform=platform,
                owner=owner,
                platform_conversation_id=platform_conversation_id,
                position=position,
            )
        return _artifact_from_row(row) if row is not None else None

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

    def mark_parsed(
        self,
        artifact_id: str,
        *,
        resume_id: str,
        parsed_name: str,
        connection: Any | None = None,
    ) -> None:
        """Mark an artifact parsed and store the generated resume id."""

        now = _now_iso()
        if connection is not None:
            connection.execute(
                """
                UPDATE resume_artifacts
                SET parse_status = 'parsed', parsed_name = ?, resume_id = ?,
                    error = '', updated_at = ?
                WHERE id = ?
                """,
                (parsed_name, resume_id, now, artifact_id),
            )
            return
        with connect(self.database_path) as owned_connection:
            self.mark_parsed(
                artifact_id,
                resume_id=resume_id,
                parsed_name=parsed_name,
                connection=owned_connection,
            )
            owned_connection.commit()

    def mark_failed(self, artifact_id: str, error: str) -> None:
        """Mark an artifact failed while preserving its platform link."""

        now = _now_iso()
        with connect(self.database_path) as connection:
            connection.execute(
                """
                UPDATE resume_artifacts
                SET parse_status = 'failed', error = ?, updated_at = ?
                WHERE id = ? AND parse_status != 'parsed'
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
            current = parse_artifact(store, resume_repository, artifact)
        except ResumeArtifactProcessingError:
            continue
        if current.parse_status == "parsed":
            parsed.append(current)
    return parsed


class ResumeArtifactProcessingError(RuntimeError):
    """The artifact could not reach a durable parsed or failed state."""


def parse_artifact(
    store: ResumeArtifactStore,
    resume_repository: ResumeRepository,
    artifact: ResumeArtifact,
) -> ResumeArtifact:
    """Parse one downloaded artifact without scanning the pending backlog."""

    current = store.get(artifact.id) or artifact
    if current.parse_status == "parsed":
        return current
    try:
        text = _read_resume_text(Path(current.file_path))
        document_name = parse_resume_name(text)
        parsed_name = choose_resume_name(
            platform_name=current.candidate_name_from_platform,
            document_name=document_name,
            file_name=current.file_path,
        )
        resume_id = _resume_id(current)
        job_type = canonical_resume_job_type(current.position) or current.position
        resume = Resume(
            id=resume_id,
            name=parsed_name or None,
            parsed_name=parsed_name,
            applied_position=job_type or None,
            job_type=job_type or None,
            source_platform=current.platform,
            source_owner=current.owner,
            linked_session_id=current.session_id,
            linked_platform=current.platform,
            linked_owner=current.owner,
            linked_platform_conversation_id=current.platform_conversation_id,
            source_artifact_id=current.id,
            updated_at=_now_iso(),
            payload={
                "name": parsed_name,
                "rawText": text,
                "platform": current.platform,
                "owner": current.owner,
                "candidateNameFromPlatform": current.candidate_name_from_platform,
                "parsedNameFromDocument": document_name,
                "applied_position": job_type,
                "sourceArtifactId": current.id,
                "filePath": current.file_path,
                "fileHash": current.file_hash,
            },
        )
        with connect(store.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM resume_artifacts WHERE id = ?",
                (current.id,),
            ).fetchone()
            locked = _artifact_from_row(row) if row is not None else current
            if locked.parse_status == "parsed":
                return locked
            resume_repository.save_in_transaction(resume, connection)
            store.mark_parsed(
                current.id,
                resume_id=resume_id,
                parsed_name=parsed_name,
                connection=connection,
            )
            connection.commit()
    except Exception as error:
        try:
            store.mark_failed(current.id, str(error))
        except Exception as mark_error:
            raise ResumeArtifactProcessingError(
                f"{error}; mark_failed_error={mark_error}"
            ) from error
    return store.get(current.id) or current


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
    if data.startswith(b"PK"):
        extracted = _read_docx_text(path)
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


def _read_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            document_xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(document_xml)
    except (KeyError, OSError, ElementTree.ParseError, zipfile.BadZipFile):
        return ""

    paragraphs: list[str] = []
    for paragraph in root.iter():
        if not paragraph.tag.endswith("}p"):
            continue
        text = "".join(
            str(node.text or "") for node in paragraph.iter() if node.tag.endswith("}t")
        ).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


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


def _find_business_download_row(
    connection: Any,
    *,
    session_id: str,
    platform: str,
    owner: str,
    platform_conversation_id: str,
    position: str,
) -> Any | None:
    session_key = str(session_id or "").strip()
    position_key = canonical_resume_job_type(position)
    if session_key:
        row = connection.execute(
            """
            SELECT * FROM resume_artifacts
            WHERE session_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (session_key,),
        ).fetchone()
        if row is not None:
            return row
    platform_id = str(platform_conversation_id or "").strip()
    if not platform_id or not position_key:
        return None
    rows = connection.execute(
        """
        SELECT * FROM resume_artifacts
        WHERE platform = ? AND owner = ? AND platform_conversation_id = ?
        ORDER BY created_at DESC
        """,
        (platform, owner, platform_id),
    ).fetchall()
    for row in rows:
        row_position = canonical_resume_job_type(row["position"])
        if row_position and row_position == position_key:
            return row
    return None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
