"""Domain exception types and their RFC 7807 problem type URIs.

[FR-01] Errors raised by the task service/repository and mapped to
problem+json by ``api.error_handlers``.

Citations: SPEC.md L88-91 (FR-01 422/404); SPEC.md L331-346 (7 error table).
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
    def type_uri(self) -> str:
        """[FR-01] Problem ``type`` URI, e.g. ``/errors/not-found``.

        Citations: SPEC.md L336-346.
        """
        return f"/errors/{self.slug}"


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
