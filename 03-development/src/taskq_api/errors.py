"""Domain exception types and their RFC 7807 problem type URIs.

[FR-01] Errors raised by the task service/repository and mapped to
problem+json by ``api.error_handlers``.
[FR-10] One subclass per row of the SPEC §7 error table; ``InternalError``
is the generic 500 fallback rendered by ``api.middleware``.

Citations: SPEC.md L88-91 (FR-01 422/404); SPEC.md L162-168 (FR-10);
SPEC.md L331-346 (7 error table).
"""

from __future__ import annotations


class TaskqError(Exception):
    """[FR-01] Base domain error carrying HTTP status and problem type slug.

    Citations: SPEC.md L331-346.
    """

    status = 500
    slug = "internal"
    title = "Internal Server Error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    @property
    def headers(self) -> dict[str, str]:
        """[FR-05] Extra response headers for the problem response (none by default).

        Citations: SPEC.md L118.
        """
        return {}

    @property
    def type_uri(self) -> str:
        """[FR-01] Problem ``type`` URI, e.g. ``/errors/not-found``.

        Citations: SPEC.md L336-346.
        """
        return f"/errors/{self.slug}"


class InternalError(TaskqError):
    """[FR-10] Unhandled failure -> 500 with a fixed, generic ``detail``.

    The detail never carries the original exception text, so SQL, stack
    traces, file paths and schema names cannot leak into the body.

    Citations: SPEC.md L166, L344.
    """

    GENERIC_DETAIL = "An internal error occurred."

    def __init__(self) -> None:
        super().__init__(self.GENERIC_DETAIL)


class ValidationFailed(TaskqError):
    """[FR-01] Input violates a validation rule -> 422.

    Citations: SPEC.md L88, L91, L338.
    """

    status = 422
    slug = "validation"
    title = "Validation Failed"


class NotFound(TaskqError):
    """[FR-01] Unknown resource id -> 404.

    Citations: SPEC.md L89, L341.
    """

    status = 404
    slug = "not-found"
    title = "Not Found"


class Conflict(TaskqError):
    """[FR-01] Task name already in use -> 409.

    Citations: SPEC.md L88, L342.
    """

    status = 409
    slug = "conflict"
    title = "Conflict"


class Unauthenticated(TaskqError):
    """[FR-03] Missing, unknown or revoked API key -> 401.

    Citations: SPEC.md L103, L106, L337.
    """

    status = 401
    slug = "unauthenticated"
    title = "Unauthenticated"


class Forbidden(TaskqError):
    """[FR-09] Key scope below the endpoint's required scope -> 403.

    Citations: SPEC.md L112, L339.
    """

    status = 403
    slug = "forbidden"
    title = "Forbidden"


class NotReady(TaskqError):
    """[FR-09] DB unavailable or migration not at head -> 503.

    Citations: SPEC.md L157, L343.
    """

    status = 503
    slug = "not-ready"
    title = "Service Unavailable"


class RateLimited(TaskqError):
    """[FR-05] Caller's token bucket is empty -> 429 with ``Retry-After``.

    Citations: SPEC.md L118, L342.
    """

    status = 429
    slug = "rate-limited"
    title = "Too Many Requests"

    def __init__(self, detail: str, retry_after_s: int) -> None:
        super().__init__(detail)
        self.retry_after_s = retry_after_s

    @property
    def headers(self) -> dict[str, str]:
        """[FR-05] ``Retry-After`` in whole seconds.

        Citations: SPEC.md L118.
        """
        return {"Retry-After": str(self.retry_after_s)}
