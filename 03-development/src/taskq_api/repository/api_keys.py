"""``api_keys`` queries.

[FR-03] Inserts hashed keys and looks a key up by its SHA-256 digest.

Citations: SPEC.md L101-107 (FR-03); SPEC.md L310 (api_keys columns);
02-architecture/SAD.md L99, L176.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from taskq_api.models.api_key import ApiKey


class ApiKeyRepository:
    """[FR-03] API key access bound to one session.

    Citations: SPEC.md L104, L310.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, api_key: ApiKey) -> ApiKey:
        """[FR-03] Insert a key row (hash only).

        Citations: SPEC.md L104-105.
        """
        self._session.add(api_key)
        self._session.flush()
        return api_key

    def get_by_hash(self, key_hash: str) -> ApiKey | None:
        """[FR-03] Fetch the key whose ``key_hash`` equals ``key_hash``.

        Citations: SPEC.md L104.
        """
        return self._session.scalars(select(ApiKey).where(ApiKey.key_hash == key_hash)).first()
