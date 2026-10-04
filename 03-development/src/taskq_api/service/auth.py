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


def hash_key(plaintext: str) -> str:
    """[FR-03] Return the 64-hex SHA-256 digest stored in ``api_keys.key_hash``.

    Citations: SPEC.md L104.
    """
    return hashlib.sha256(plaintext.encode()).hexdigest()


def create_key(uow: UnitOfWork, scope: str) -> str:
    """[FR-03] Persist a new key of ``scope`` and return its plaintext (never stored).

    Citations: SPEC.md L104-105.
    """
    plaintext = KEY_PREFIX + secrets.token_urlsafe(32)
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
    if (
        api_key is None
        or not hmac.compare_digest(api_key.key_hash, digest)
        or api_key.revoked_at is not None
    ):
        raise Unauthenticated("invalid API key")
    return api_key
