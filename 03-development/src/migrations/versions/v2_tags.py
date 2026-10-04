"""v2: ``tags`` / ``task_tags`` (many-to-many) and a unique index on ``tasks.name``.

[FR-07] Downgrade removes only the v2 objects; v1 rows are untouched.

Citations: SPEC.md L137 (v2 row); SPEC.md L310-311 (tags, task_tags).
"""

import sqlalchemy as sa
from alembic import op

revision = "v2"
down_revision = "v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """[FR-07] Add tag tables and the unique task name index. Citations: SPEC.md L137."""
    op.create_table(
        "tags",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("label", sa.String(255), nullable=False, unique=True),
    )
    op.create_table(
        "task_tags",
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), primary_key=True),
        sa.Column("tag_id", sa.String(36), sa.ForeignKey("tags.id"), primary_key=True),
    )
    op.create_index("uq_tasks_name", "tasks", ["name"], unique=True)


def downgrade() -> None:
    """[FR-07] Remove the v2 index and tables. Citations: SPEC.md L137."""
    op.drop_index("uq_tasks_name", table_name="tasks")
    op.drop_table("task_tags")
    op.drop_table("tags")
