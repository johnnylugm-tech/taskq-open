"""UnitOfWork type re-exported for the API layer.

[FR-01] Lets ``api`` obtain a transaction scope without importing ``repository``.

Citations: SPEC.md L125 (FR-06); 02-architecture/SAD.md L20, L62.
"""

from taskq_api.repository.session import UnitOfWork

__all__ = ["UnitOfWork"]
