"""``rate_buckets`` queries.

[FR-05] Reads a key's bucket under a row-level lock (``SELECT ... FOR UPDATE``)
and writes it back inside the caller's transaction.

Citations: SPEC.md L119 (single transaction, row-level lock);
02-architecture/SAD.md L77, L165.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from taskq_api.models.rate_bucket import RateBucket


class RateBucketRepository:
    """[FR-05] Bucket access bound to one session.

    Citations: SPEC.md L119.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_update(self, key_id: str) -> RateBucket | None:
        """[FR-05] Fetch ``key_id``'s bucket, row-locked until the transaction ends.

        Citations: SPEC.md L119.
        """
        stmt = select(RateBucket).where(RateBucket.key_id == key_id).with_for_update()
        return self._session.scalars(stmt).first()

    def save(self, bucket: RateBucket | None, key_id: str, tokens: float, now: datetime) -> None:
        """[FR-05] Insert the bucket on first use, else update the locked row.

        Citations: SPEC.md L117, L119.
        """
        if bucket is None:
            self._session.add(RateBucket(key_id=key_id, tokens=tokens, updated_at=now))
        else:
            bucket.tokens = tokens
            bucket.updated_at = now
        self._session.flush()
