"""NFR-12 smoke probe: start the real service and exercise it over HTTP.

Requires 200 from /healthz and /readyz, then, with an API key issued by the
caller through ``python -m taskq_api key create`` (``TASKQ_SMOKE_KEY``), creates
a task, runs it through the live executor and waits for ``done``.

Usage: python scripts/smoke_probe.py
The database comes from ``TASKQ_DB_URL`` (already migrated to head by the caller).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "03-development" / "src"
PATHS = ("/healthz", "/readyz")
STARTUP_DEADLINE_SECONDS = 30.0


def fetch_status(url: str) -> int:
    """Return the HTTP status of ``url``."""
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status


def call(method: str, url: str, key: str, body: dict | None = None) -> tuple[int, dict]:
    """Send one authenticated JSON request; return ``(status, parsed body)``."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("X-API-Key", key)
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = response.read()
        return response.status, json.loads(payload) if payload else {}


def run_task_end_to_end(base: str, key: str) -> str | None:
    """Create a task, run it and wait for ``done``; return an error message or None."""
    status, task = call("POST", base + "/v1/tasks", key, {"name": "smoke", "command": "echo smoke"})
    if status != 201:
        return f"create task returned {status}"
    status, _ = call("POST", f"{base}/v1/tasks/{task['id']}/run", key)
    if status != 202:
        return f"run task returned {status}"
    deadline = time.monotonic() + STARTUP_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        _, current = call("GET", f"{base}/v1/tasks/{task['id']}", key)
        if current["status"] == "done":
            return None
        time.sleep(0.2)
    return "task did not reach done"


def free_port() -> int:
    """Return a TCP port that is currently free on the loopback interface."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until_up(base: str, server: subprocess.Popen) -> bool:
    """Poll ``/healthz`` until it answers; False if the server exits or the deadline passes."""
    deadline = time.monotonic() + STARTUP_DEADLINE_SECONDS
    while server.poll() is None and time.monotonic() < deadline:
        try:
            fetch_status(base + PATHS[0])
            return True
        except OSError:
            time.sleep(0.2)
    return False


def main() -> int:
    """Run the service, probe every path, stop the service; 0 only if all answer 200."""
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "taskq_api.app:create_app", "--factory",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env,
    )
    try:
        if not wait_until_up(base, server):
            print("verify-system: service did not start", file=sys.stderr)
            return 1
        for path in PATHS:
            status = fetch_status(base + path)
            if status != 200:
                print(f"verify-system: {path} returned {status}", file=sys.stderr)
                return 1
        key = os.environ.get("TASKQ_SMOKE_KEY")
        problem = run_task_end_to_end(base, key) if key else "TASKQ_SMOKE_KEY is not set"
        if problem:
            print(f"verify-system: {problem}", file=sys.stderr)
            return 1
        return 0
    finally:
        server.terminate()
        server.wait(timeout=30)


if __name__ == "__main__":
    sys.exit(main())
