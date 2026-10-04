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

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
TIMEOUT = "timeout"

TRANSITIONS = {
    PENDING: frozenset({RUNNING}),
    RUNNING: frozenset({DONE, FAILED, TIMEOUT}),
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
        self.state = PENDING
        self.history = [PENDING]

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

    On timeout the process is killed and reaped so no orphan is left. A
    command that cannot be spawned (empty, unparsable or not found) ends
    ``failed`` with no exit code and the reason in ``stderr_tail``, rather
    than leaving the run stuck in ``running``.

    Citations: SPEC.md L96-98, L149, L293.
    """
    timeout = load_settings().task_timeout
    started = time.monotonic()
    machine.transition(RUNNING)
    exit_code: int | None = None
    try:
        argv = shlex.split(command)
        if not argv:
            raise ValueError("empty command")
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, ValueError) as exc:
        stdout, stderr, status = b"", str(exc).encode(), FAILED
    else:
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
            status = DONE if process.returncode == 0 else FAILED
        except TimeoutError:
            process.kill()
            await process.wait()
            stdout, stderr, status = b"", b"", TIMEOUT
        exit_code = process.returncode
    machine.transition(status)
    return RunOutcome(
        status=status,
        exit_code=exit_code,
        stdout_tail=tail(stdout),
        stderr_tail=tail(stderr),
        duration_ms=int((time.monotonic() - started) * 1000),
        finished_at=datetime.now(timezone.utc),
    )
