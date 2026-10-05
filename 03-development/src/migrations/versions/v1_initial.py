"""v1: initial schema — ``tasks`` (with ``result_json``), ``api_keys``, ``rate_buckets``.

[FR-07] Downgrade removes the three v1 tables.

Citations: SPEC.md L136 (v1 row); SPEC.md L308-309, L313, L315 (5.2 schema).
"""
# pragma: no error-handling — runs inside one alembic transaction; a failing revision rolls back (NFR-03 AC-N3.6)

import sqlalchemy as sa
from alembic import op

revision = "v1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """[FR-07] Create the v1 tables. Citations: SPEC.md L136, L308-315."""
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("result_json", sa.Text()),
    )
    op.create_index("ix_tasks_status_created_at", "tasks", ["status", "created_at"])
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("revoked_at", sa.String(40)),
    )
    op.create_table(
        "rate_buckets",
        sa.Column("key_id", sa.String(36), sa.ForeignKey("api_keys.id"), primary_key=True),
        sa.Column("tokens", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )


def downgrade() -> None:
    """[FR-07] Remove the v1 tables, dependants first. Citations: SPEC.md L136."""
    op.drop_table("rate_buckets")
    op.drop_table("api_keys")
    op.drop_index("ix_tasks_status_created_at", table_name="tasks")
    op.drop_table("tasks")
