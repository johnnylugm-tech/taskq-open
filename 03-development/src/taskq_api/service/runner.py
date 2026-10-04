"""Subprocess execution and the run state machine.

[FR-02] Runs a task command via ``asyncio.create_subprocess_exec`` on its
``shlex.split`` argv (never a shell), enforces ``TASKQ_TASK_TIMEOUT`` and
drives ``pending -> running -> done | failed | timeout``.

Citations: SPEC.md L93-99 (FR-02); SPEC.md L149 (kill then wait on timeout);
SPEC.md L209-210 (NFR-04 redaction); SPEC.md L293 (TASKQ_TASK_TIMEOUT).
"""

from __future__ import annotations

import asyncio
import shlex
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from taskq_api.config import load_settings
from taskq_api.service.redact import redact

TAIL_CHARS = 4096
TRANSITIONS = {
    "pending": frozenset({"running"}),
    "running": frozenset({"done", "failed", "timeout"}),
}


class InvalidTransition(Exception):
    """[FR-02] Raised for a move not allowed by the run state machine.

    Citations: SPEC.md L97.
    """


class TaskStateMachine:
    """[FR-02] ``pending -> running -> done | failed | timeout``; terminal states are final.

    Citations: SPEC.md L97.
    """

    def __init__(self) -> None:
        self.state = "pending"
        self.history = ["pending"]

    def transition(self, to: str) -> None:
        """[FR-02] Enter ``to`` or raise :class:`InvalidTransition`.

        Citations: SPEC.md L97.
        """
        if to not in TRANSITIONS.get(self.state, frozenset()):
            raise InvalidTransition(f"{self.state} -> {to}")
        self.state = to
        self.history.append(to)


@dataclass(frozen=True)
class RunOutcome:
    """[FR-02] Final status plus the ``task_results`` column values.

    Citations: SPEC.md L97-98.
    """

    status: str
    exit_code: int | None
    stdout_tail: str
    stderr_tail: str
    duration_ms: int
    finished_at: datetime


def tail(raw: bytes) -> str:
    """[FR-02] Decode, redact, then keep the last ``TAIL_CHARS`` characters.

    Redacting before truncation keeps a cut-off secret from escaping the regex.

    Citations: SPEC.md L98, L209-210.
    """
    return redact(raw.decode(errors="replace"))[-TAIL_CHARS:]


async def run_command(command: str, machine: TaskStateMachine) -> RunOutcome:
    """[FR-02] Execute ``command`` without a shell under ``TASKQ_TASK_TIMEOUT``.

    On timeout the process is killed and reaped so no orphan is left.

    Citations: SPEC.md L96-98, L149, L293.
    """
    timeout = load_settings().task_timeout
    started = time.monotonic()
    machine.transition("running")
    process = await asyncio.create_subprocess_exec(
        *shlex.split(command),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
        status = "done" if process.returncode == 0 else "failed"
    except TimeoutError:
        process.kill()
        await process.wait()
        stdout, stderr, status = b"", b"", "timeout"
    machine.transition(status)
    return RunOutcome(
        status=status,
        exit_code=process.returncode,
        stdout_tail=tail(stdout),
        stderr_tail=tail(stderr),
        duration_ms=int((time.monotonic() - started) * 1000),
        finished_at=datetime.now(timezone.utc),
    )
