"""API key hashing, issuance and verification.

[FR-03] Keys are stored as SHA-256 digests only; a presented key is hashed,
looked up, compared with ``hmac.compare_digest`` and rejected when revoked.

Citations: SPEC.md L101-107 (FR-03); SPEC.md L337 (401 problem type);
02-architecture/SAD.md L67, L99, L176.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone

from taskq_api.errors import Unauthenticated
from taskq_api.models.api_key import ApiKey
from taskq_api.service.uow import UnitOfWork

SCOPES = ("read", "write", "admin")
KEY_PREFIX = "tq_"
KEY_ENTROPY_BYTES = 32


def hash_key(plaintext: str) -> str:
    """[FR-03] Return the 64-hex SHA-256 digest stored in ``api_keys.key_hash``.

    Citations: SPEC.md L104.
    """
    return hashlib.sha256(plaintext.encode()).hexdigest()


def _new_plaintext() -> str:
    """[FR-03] Generate a fresh random plaintext key.

    Citations: SPEC.md L105.
    """
    return KEY_PREFIX + secrets.token_urlsafe(KEY_ENTROPY_BYTES)


def create_key(uow: UnitOfWork, scope: str) -> str:
    """[FR-03] Persist a new key of ``scope`` and return its plaintext (never stored).

    Citations: SPEC.md L104-105.
    """
    plaintext = _new_plaintext()
    uow.api_keys.add(
        ApiKey(
            id=str(uuid.uuid4()),
            key_hash=hash_key(plaintext),
            scope=scope,
            created_at=datetime.now(timezone.utc),
        )
    )
    return plaintext


def verify(uow: UnitOfWork, presented: str | None) -> ApiKey:
    """[FR-03] Return the active key matching ``presented``, else raise 401.

    Citations: SPEC.md L103-104, L106.
    """
    if not presented:
        raise Unauthenticated("missing API key")
    digest = hash_key(presented)
    api_key = uow.api_keys.get_by_hash(digest)
    if api_key is None or not _is_active(api_key, digest):
        raise Unauthenticated("invalid API key")
    return api_key


def _is_active(api_key: ApiKey, digest: str) -> bool:
    """[FR-03] True when ``api_key`` matches ``digest`` and has not been revoked.

    Citations: SPEC.md L104, L106.
    """
    return hmac.compare_digest(api_key.key_hash, digest) and api_key.revoked_at is None
