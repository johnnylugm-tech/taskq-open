"""ORM models of the SPEC 5.2 head schema.

[FR-01] Importing this package registers every table on ``Base.metadata``.

Citations: SPEC.md L304-316 (5.2 database schema).
"""

from taskq_api.models import api_key, result, tag, task  # noqa: F401
