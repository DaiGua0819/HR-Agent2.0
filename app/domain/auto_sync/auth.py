"""Authenticated encryption helpers for automatic synchronization requests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Mapping

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SYNC_PROTOCOL_VERSION = "auto-sync-v1"
SYNC_MAX_CLOCK_SKEW_SECONDS = 300


class SyncAuthenticationError(ValueError):
    """Raised when an automatic synchronization request cannot be trusted."""


def build_encrypted_sync_request(
    plaintext: bytes,
    secret: str,
    *,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> tuple[bytes, dict[str, str]]:
    """Encrypt a request body and return the matching signed headers."""

    resolved_timestamp = int(timestamp if timestamp is not None else time.time())
    resolved_nonce = nonce or secrets.token_hex(16)
    iv = secrets.token_bytes(12)
    aad = _aad(resolved_timestamp, resolved_nonce)
    ciphertext = AESGCM(_encryption_key(secret)).encrypt(iv, plaintext, aad)
    envelope = json.dumps(
        {
            "version": SYNC_PROTOCOL_VERSION,
            "iv": base64.b64encode(iv).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return envelope, build_sync_headers(
        envelope,
        secret,
        timestamp=resolved_timestamp,
        nonce=resolved_nonce,
    )


def build_sync_headers(
    transmitted_body: bytes,
    secret: str,
    *,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    resolved_timestamp = int(timestamp if timestamp is not None else time.time())
    resolved_nonce = nonce or secrets.token_hex(16)
    signature = _signature(
        transmitted_body,
        secret,
        timestamp=resolved_timestamp,
        nonce=resolved_nonce,
    )
    return {
        "Content-Type": "application/octet-stream",
        "X-Sync-Timestamp": str(resolved_timestamp),
        "X-Sync-Nonce": resolved_nonce,
        "X-Sync-Signature": signature,
        "X-Sync-Protocol": SYNC_PROTOCOL_VERSION,
    }


def verify_and_decrypt_sync_request(
    transmitted_body: bytes,
    headers: Mapping[str, str],
    secret: str,
    *,
    now: int | None = None,
) -> bytes:
    """Verify freshness/signature and decrypt a synchronization request."""

    if not secret:
        raise SyncAuthenticationError("auto_sync_secret_not_configured")
    try:
        timestamp = int(headers.get("x-sync-timestamp", ""))
    except ValueError as error:
        raise SyncAuthenticationError("auto_sync_timestamp_invalid") from error
    nonce = str(headers.get("x-sync-nonce", ""))
    provided_signature = str(headers.get("x-sync-signature", ""))
    protocol = str(headers.get("x-sync-protocol", ""))
    if not timestamp or not nonce or not provided_signature:
        raise SyncAuthenticationError("auto_sync_auth_headers_missing")
    if protocol != SYNC_PROTOCOL_VERSION:
        raise SyncAuthenticationError("auto_sync_protocol_invalid")
    current_time = int(now if now is not None else time.time())
    if abs(current_time - timestamp) > SYNC_MAX_CLOCK_SKEW_SECONDS:
        raise SyncAuthenticationError("auto_sync_request_stale")
    expected_signature = _signature(
        transmitted_body,
        secret,
        timestamp=timestamp,
        nonce=nonce,
    )
    if not hmac.compare_digest(provided_signature, expected_signature):
        raise SyncAuthenticationError("auto_sync_signature_invalid")
    try:
        envelope = json.loads(transmitted_body)
        if envelope.get("version") != SYNC_PROTOCOL_VERSION:
            raise SyncAuthenticationError("auto_sync_envelope_invalid")
        iv = base64.b64decode(envelope["iv"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        return AESGCM(_encryption_key(secret)).decrypt(
            iv,
            ciphertext,
            _aad(timestamp, nonce),
        )
    except SyncAuthenticationError:
        raise
    except Exception as error:
        raise SyncAuthenticationError("auto_sync_decryption_failed") from error


def _signature(body: bytes, secret: str, *, timestamp: int, nonce: str) -> str:
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{timestamp}\n{nonce}\n{body_hash}".encode()
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _encryption_key(secret: str) -> bytes:
    if not secret:
        raise SyncAuthenticationError("auto_sync_secret_not_configured")
    return hashlib.sha256(f"{SYNC_PROTOCOL_VERSION}:{secret}".encode()).digest()


def _aad(timestamp: int, nonce: str) -> bytes:
    return f"{SYNC_PROTOCOL_VERSION}\n{timestamp}\n{nonce}".encode()
