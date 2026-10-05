"""v3: move ``tasks.result_json`` into the ``task_results`` table.

[FR-07] Upgrade copies every result out of ``tasks.result_json`` (a JSON array
of result objects, or a single object written by v1 code) and then removes the
column. Downgrade folds each task's results back into ``result_json`` as a JSON
array before removing ``task_results``, so a round trip keeps every column
value and its type. Both directions are plain SQL so offline mode renders them.

Citations: SPEC.md L138 (v3 row); SPEC.md L141-142 (round trip, no shortcut);
SPEC.md L312, L315 (task_results, result_json).
"""
# pragma: no error-handling — runs inside one alembic transaction; a failing revision rolls back (NFR-03 AC-N3.6)

from typing import Any, cast

import sqlalchemy as sa
from alembic import op

revision = "v3"
down_revision = "v2"
branch_labels = None
depends_on = None

# Result columns carried between ``tasks.result_json`` and ``task_results``;
# the single source for the table schema.
_RESULT_COLUMNS = (
    ("exit_code", sa.Integer),
    ("stdout_tail", sa.Text),
    ("stderr_tail", sa.Text),
    ("duration_ms", sa.Integer),
    ("finished_at", lambda: sa.String(40)),
)

# Literal SQL (no string-built statements, NFR-02): the column lists below must
# match ``_RESULT_COLUMNS``.
_SPLIT_RESULTS = (
    "INSERT INTO task_results (id, task_id, exit_code, stdout_tail, stderr_tail, duration_ms, finished_at) "
    "SELECT COALESCE(json_extract(r.value, '$.id'), lower(hex(randomblob(16)))), t.id, "
    "json_extract(r.value, '$.exit_code'), json_extract(r.value, '$.stdout_tail'), "
    "json_extract(r.value, '$.stderr_tail'), json_extract(r.value, '$.duration_ms'), "
    "json_extract(r.value, '$.finished_at') "
    "FROM tasks AS t, json_each(CASE WHEN json_type(t.result_json) = 'array' "
    "THEN t.result_json ELSE json_array(json(t.result_json)) END) AS r "
    "WHERE t.result_json IS NOT NULL"
)

_FOLD_RESULTS = (
    "UPDATE tasks SET result_json = ("
    "SELECT json_group_array(json_object('id', r.id, 'exit_code', r.exit_code, "
    "'stdout_tail', r.stdout_tail, 'stderr_tail', r.stderr_tail, "
    "'duration_ms', r.duration_ms, 'finished_at', r.finished_at)) "
    "FROM task_results AS r WHERE r.task_id = tasks.id) "
    "WHERE EXISTS (SELECT 1 FROM task_results AS r WHERE r.task_id = tasks.id)"
)


def upgrade() -> None:
    """[FR-07] Create ``task_results``, migrate data, remove ``result_json``.

    Citations: SPEC.md L138, L312.
    """
    op.create_table(
        "task_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id")),
        *(sa.Column(name, cast("sa.types.TypeEngine[Any]", column_type())) for name, column_type in _RESULT_COLUMNS),
    )
    op.create_index("ix_task_results_task_id", "task_results", ["task_id"])
    op.execute(_SPLIT_RESULTS)
    op.drop_column("tasks", "result_json")


def downgrade() -> None:
    """[FR-07] Restore ``result_json`` from ``task_results``, then remove it.

    Citations: SPEC.md L138, L141-142.
    """
    op.add_column("tasks", sa.Column("result_json", sa.Text()))
    op.execute(_FOLD_RESULTS)
    op.drop_index("ix_task_results_task_id", table_name="task_results")
    op.drop_table("task_results")
