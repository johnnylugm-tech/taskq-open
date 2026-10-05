"""Secret redaction applied before output is persisted or sent.

[FR-02] Masks secrets in captured ``stdout_tail`` / ``stderr_tail`` (NFR-04).

Citations: SPEC.md L98 (FR-02 output tails); SPEC.md L207-210 (NFR-04 regex).
"""
# pragma: no error-handling — pure string function, cannot fail

from __future__ import annotations

import re

REDACTED = "[REDACTED]"
SECRET_PATTERN = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|token=\S+|Bearer\s+\S+|postgres(ql)?://[^\s]+)")


def redact(text: str) -> str:
    """[FR-02] Replace every line matching the secret pattern with ``[REDACTED]``.

    Citations: SPEC.md L209-210.
    """
    return "".join(
        REDACTED + line[len(line.rstrip("\r\n")) :] if SECRET_PATTERN.search(line) else line
        for line in text.splitlines(keepends=True)
    )
