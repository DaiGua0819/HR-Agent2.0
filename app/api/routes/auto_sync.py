"""Encrypted internal API used by the local automatic synchronization worker."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from app.domain.auto_sync.auth import (
    SyncAuthenticationError,
    verify_and_decrypt_sync_request,
)
from app.domain.auto_sync.models import SyncBatch
from app.domain.auto_sync.service import AutoSyncConflict, AutoSyncService

router = APIRouter(prefix="/api/internal/sync", tags=["internal-sync"])
_MAX_ENCRYPTED_BATCH_BYTES = 30 * 1024 * 1024


@router.post("/batch")
async def apply_sync_batch(request: Request) -> dict[str, object]:
    transmitted_body = await request.body()
    if not transmitted_body or len(transmitted_body) > _MAX_ENCRYPTED_BATCH_BYTES:
        raise HTTPException(status_code=413, detail="auto_sync_batch_size_invalid")
    secret = str(getattr(request.app.state, "auto_sync_secret", "") or "")
    try:
        plaintext = verify_and_decrypt_sync_request(
            transmitted_body,
            request.headers,
            secret,
        )
    except SyncAuthenticationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    try:
        batch = SyncBatch.model_validate_json(plaintext)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail="auto_sync_batch_invalid") from error
    service = getattr(request.app.state, "auto_sync_service", None)
    if not isinstance(service, AutoSyncService):
        raise HTTPException(status_code=503, detail="auto_sync_service_unavailable")
    try:
        return service.apply_batch(batch, body_hash=hashlib.sha256(plaintext).hexdigest())
    except AutoSyncConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
