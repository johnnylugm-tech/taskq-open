"""Command-line entry point (``python -m taskq_api``).

[FR-03] ``key create --scope <scope>`` issues an API key and prints its
plaintext exactly once.

Citations: SPEC.md L105 (key create); 02-architecture/SAD.md L44-45.
"""

from __future__ import annotations

import argparse

import uvicorn

from taskq_api.config import load_settings
from taskq_api.repository.session import build_engine, uow_factory
from taskq_api.service import auth


def key_create(args: argparse.Namespace) -> int:
    """[FR-03] Insert one ``api_keys`` row and print the plaintext key once.

    Citations: SPEC.md L104-105.
    """
    engine = build_engine(load_settings())
    try:
        with uow_factory(engine)() as uow:
            plaintext = auth.create_key(uow, args.scope)
    finally:
        engine.dispose()
    print(plaintext)
    return 0


def serve(args: argparse.Namespace) -> int:
    """[FR-03] Run the ASGI app on ``TASKQ_HOST`` / ``TASKQ_PORT``.

    Citations: SPEC.md L301-302.
    """
    settings = load_settings()
    uvicorn.run(
        "taskq_api.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_config=None,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """[FR-03] Build the ``taskq_api`` argument parser.

    Citations: SPEC.md L105.
    """
    parser = argparse.ArgumentParser(prog="taskq_api")
    commands = parser.add_subparsers(dest="command", required=True)
    key = commands.add_parser("key", help="manage API keys")
    key_commands = key.add_subparsers(dest="key_command", required=True)
    create = key_commands.add_parser("create", help="issue a new API key")
    create.add_argument("--scope", required=True, choices=auth.SCOPES)
    create.set_defaults(handler=key_create)
    commands.add_parser("serve", help="run the API server").set_defaults(handler=serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    """[FR-03] Parse ``argv`` and run the selected command; returns the exit code.

    Citations: SPEC.md L105.
    """
    args = build_parser().parse_args(argv)
    return args.handler(args)
