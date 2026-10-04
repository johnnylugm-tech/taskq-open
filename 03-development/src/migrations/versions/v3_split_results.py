"""v3: move ``tasks.result_json`` into the ``task_results`` table.

[FR-07] Upgrade copies every result out of ``tasks.result_json`` (a JSON array
of result objects, or a single object written by v1 code) and then removes the
column. Downgrade folds each task's results back into ``result_json`` as a JSON
array before removing ``task_results``, so a round trip keeps every column
value and its type. Both directions are plain SQL so offline mode renders them.

Citations: SPEC.md L138 (v3 row); SPEC.md L141-142 (round trip, no shortcut);
SPEC.md L312, L315 (task_results, result_json).
"""

import sqlalchemy as sa
from alembic import op

revision = "v3"
down_revision = "v2"
branch_labels = None
depends_on = None

# Result columns carried between ``tasks.result_json`` and ``task_results``;
# the single source for the table schema and both data-migration statements.
_RESULT_COLUMNS = (
    ("exit_code", sa.Integer),
    ("stdout_tail", sa.Text),
    ("stderr_tail", sa.Text),
    ("duration_ms", sa.Integer),
    ("finished_at", lambda: sa.String(40)),
)
_FIELDS = tuple(name for name, _ in _RESULT_COLUMNS)

_SPLIT_RESULTS = (
    "INSERT INTO task_results (id, task_id, {cols}) "
    "SELECT COALESCE(json_extract(r.value, '$.id'), lower(hex(randomblob(16)))), t.id, {extracts} "
    "FROM tasks AS t, json_each(CASE WHEN json_type(t.result_json) = 'array' "
    "THEN t.result_json ELSE json_array(json(t.result_json)) END) AS r "
    "WHERE t.result_json IS NOT NULL"
).format(
    cols=", ".join(_FIELDS),
    extracts=", ".join(f"json_extract(r.value, '$.{f}')" for f in _FIELDS),
)

_FOLD_RESULTS = (
    "UPDATE tasks SET result_json = ("
    "SELECT json_group_array(json_object('id', r.id, {pairs})) "
    "FROM task_results AS r WHERE r.task_id = tasks.id) "
    "WHERE EXISTS (SELECT 1 FROM task_results AS r WHERE r.task_id = tasks.id)"
).format(pairs=", ".join(f"'{f}', r.{f}" for f in _FIELDS))


def upgrade() -> None:
    """[FR-07] Create ``task_results``, migrate data, remove ``result_json``.

    Citations: SPEC.md L138, L312.
    """
    op.create_table(
        "task_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id")),
        *(sa.Column(name, column_type()) for name, column_type in _RESULT_COLUMNS),
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
