"""``python -m taskq_api`` entry point.

[FR-03] Delegates to :func:`taskq_api.cli.main`.

Citations: SPEC.md L105; 02-architecture/SAD.md L43.
"""

import sys

from taskq_api.cli import main

if __name__ == "__main__":
    sys.exit(main())
