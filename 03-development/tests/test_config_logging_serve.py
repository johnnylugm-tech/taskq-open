"""TASKQ_LOG_LEVEL / TASKQ_LOG_FORMAT / TASKQ_HOST / TASKQ_PORT are read and applied."""

from __future__ import annotations

import json
import logging
import sys

import pytest

from taskq_api import cli
from taskq_api.app import JsonFormatter, configure_logging
from taskq_api.config import Settings, load_settings


@pytest.fixture
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_config_defaults(monkeypatch):
    for key in ("TASKQ_LOG_LEVEL", "TASKQ_LOG_FORMAT", "TASKQ_HOST", "TASKQ_PORT"):
        monkeypatch.delenv(key, raising=False)
    s = load_settings()
    assert (s.log_level, s.log_format, s.host, s.port) == ("INFO", "json", "127.0.0.1", 8000)


def test_config_reads_env(monkeypatch):
    monkeypatch.setenv("TASKQ_LOG_LEVEL", "debug")
    monkeypatch.setenv("TASKQ_LOG_FORMAT", "TEXT")
    monkeypatch.setenv("TASKQ_HOST", "0.0.0.0")
    monkeypatch.setenv("TASKQ_PORT", "9001")
    s = load_settings()
    assert (s.log_level, s.log_format, s.host, s.port) == ("DEBUG", "text", "0.0.0.0", 9001)


def _settings(**kw) -> Settings:
    return Settings(db_url="sqlite:///unused.db", db_pool_size=1, task_timeout=1.0, rate_burst=1,
                    rate_per_sec=1.0, max_concurrent=1, drain_timeout=1.0, **kw)


def test_configure_logging_json(restore_root_logger):
    configure_logging(_settings(log_level="WARNING", log_format="json"))
    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert isinstance(root.handlers[-1].formatter, JsonFormatter)


def test_configure_logging_text(restore_root_logger):
    configure_logging(_settings(log_level="DEBUG", log_format="text"))
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert not isinstance(root.handlers[-1].formatter, JsonFormatter)


def test_json_formatter_fields():
    fmt = JsonFormatter()
    rec = logging.LogRecord("n", logging.INFO, __file__, 1, "hi %s", ("x",), None)
    assert json.loads(fmt.format(rec)) == {"level": "INFO", "logger": "n", "message": "hi x"}
    rec.correlation_id = "cid"
    try:
        raise ValueError("boom")
    except ValueError:
        rec.exc_info = sys.exc_info()
    out = json.loads(fmt.format(rec))
    assert out["correlation_id"] == "cid" and "ValueError: boom" in out["exc_info"]


def test_serve_uses_host_and_port(monkeypatch):
    monkeypatch.setenv("TASKQ_HOST", "0.0.0.0")
    monkeypatch.setenv("TASKQ_PORT", "9001")
    calls = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: calls.append((a, k)))
    assert cli.main(["serve"]) == 0
    assert calls == [(("taskq_api.app:create_app",),
                      {"factory": True, "host": "0.0.0.0", "port": 9001, "log_config": None})]
