"""FR-07 — Schema migration (Alembic v1 -> v2 -> v3).

Covers TEST_SPEC.md FR-07 rows 1-8 (AC-7.1 .. AC-7.5, NP-04, NP-10, SEC T-09).

Test harness contract:
- Alembic revisions live in the `migrations.versions` package
  (`03-development/src/migrations/versions/{v1_initial,v2_tags,v3_split_results}.py`)
  with revision ids exactly "v1", "v2", "v3" (v1 down_revision None).
- `taskq_api.repository.migration_state` exposes:
    alembic_config(db_url: str) -> alembic.config.Config
    upgrade(db_url: str, revision: str = "head") -> int        (0 on success)
    downgrade(db_url: str, revision: str) -> int               (0 on success)
    current_revision(db_url: str) -> str | None
    offline_sql(db_url: str, start: str = "base", end: str = "head") -> str
  `offline_sql` renders the migration SQL with alembic's offline (`--sql`) mode
  and returns it as text without touching the database.
- v1 creates `tasks` (with `result_json`), `api_keys`, `rate_buckets`;
  v2 adds `tags`, `task_tags` and a unique index on `tasks.name`;
  v3 moves `tasks.result_json` into `task_results` and drops the column;
  every downgrade reverses its upgrade without losing data.

Every DB test runs against a real SQLite file under tmp_path (NFR-09); calls
are in-process so pytest-cov measures the migration modules.
"""

from __future__ import annotations

import ast
import re
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from migrations.versions import v1_initial, v2_tags, v3_split_results  # noqa: E402
from taskq_api.repository import migration_state  # noqa: E402

REVISION_MODULES = {"v1": v1_initial, "v2": v2_tags, "v3": v3_split_results}
RESULT_COLUMNS = ("id", "task_id", "exit_code", "stdout_tail", "stderr_tail", "duration_ms", "finished_at")
DROP_SHORTCUT = re.compile(r"DROP\s+TABLE", re.IGNORECASE)


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """A fresh SQLite *file* per test (state_mode=isolate_per_test)."""
    return f"sqlite:///{tmp_path / 'taskq.db'}"


def _db_file(url: str) -> Path:
    return Path(url.removeprefix("sqlite:///"))


def _backend(url: str) -> str:
    path = _db_file(url)
    if url.startswith("sqlite:///") and path.name and path.exists():
        return "sqlite-file"
    return "other"


def _connect(url: str) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_file(url))
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _tables(url: str) -> set[str]:
    with _connect(url) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows if not r[0].startswith("sqlite_")}


def _columns(url: str, table: str) -> list[str]:
    with _connect(url) as conn:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _insert_tasks(url: str, count: int, prefix: str) -> list[tuple]:
    rows = [
        (str(uuid.uuid4()), f"echo {i}", f"{prefix}-{i}", "done", f"2026-01-01T00:00:0{i}")
        for i in range(count)
    ]
    with _connect(url) as conn:
        conn.executemany(
            "INSERT INTO tasks (id, command, name, status, created_at) VALUES (?, ?, ?, ?, ?)", rows
        )
    return rows


def _select_tasks(url: str) -> list[tuple]:
    with _connect(url) as conn:
        return conn.execute(
            "SELECT id, command, name, status, created_at FROM tasks ORDER BY name"
        ).fetchall()


def _insert_results(url: str, task_ids: list[str], values: list[tuple]) -> list[tuple]:
    rows = [(str(uuid.uuid4()), tid, *vals) for tid, vals in zip(task_ids, values)]
    with _connect(url) as conn:
        conn.executemany(
            f"INSERT INTO task_results ({', '.join(RESULT_COLUMNS)}) VALUES (?, ?, ?, ?, ?, ?, ?)", rows
        )
    return sorted(rows)


def _select_results(url: str) -> list[tuple]:
    with _connect(url) as conn:
        return sorted(conn.execute(f"SELECT {', '.join(RESULT_COLUMNS)} FROM task_results").fetchall())


def _mismatched_columns(before: list[tuple], after: list[tuple]) -> list[tuple[int, str]]:
    mismatched = []
    for idx, (b_row, a_row) in enumerate(zip(before, after)):
        for col, b_val, a_val in zip(RESULT_COLUMNS, b_row, a_row):
            if b_val != a_val or type(b_val) is not type(a_val):
                mismatched.append((idx, col))
    return mismatched


def _is_trivial(func: ast.FunctionDef) -> bool:
    body = [n for n in func.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    return all(isinstance(n, ast.Pass) for n in body)


# --- 1 ---------------------------------------------------------------------


def test_fr07_three_revisions_each_with_downgrade(db_url):
    expected_revisions = "v1,v2,v3"
    expected_without_downgrade = "0"
    db_backend = "sqlite-file"

    script = ScriptDirectory.from_config(migration_state.alembic_config(db_url))
    result_revisions = [rev.revision for rev in reversed(list(script.walk_revisions("base", "heads")))]

    result_revisions_without_downgrade = []
    for rev_id, module in REVISION_MODULES.items():
        assert module.revision == rev_id
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        if "downgrade" not in funcs or _is_trivial(funcs["downgrade"]):
            result_revisions_without_downgrade.append(rev_id)

    assert migration_state.upgrade(db_url, "head") == 0
    result_db_backend = _backend(db_url)

    # AC7.1-revisions
    assert result_revisions == expected_revisions.split(",")
    # AC7.1-downgrades
    assert len(result_revisions_without_downgrade) == int(expected_without_downgrade)
    # AC7.1-backend
    assert result_db_backend == db_backend
    assert v1_initial.down_revision is None
    assert v2_tags.down_revision == "v1"
    assert v3_split_results.down_revision == "v2"


# --- 2 ---------------------------------------------------------------------


def test_fr07_upgrade_head_and_downgrade_base_clean(db_url):
    # subprocess_mode="in_process": migration_state drives alembic.command directly
    expected_upgrade_exit = "0"
    expected_downgrade_exit = "0"
    expected_residual_tables = "0"

    result_upgrade_exit = migration_state.upgrade(db_url, "head")
    assert migration_state.current_revision(db_url) == "v3"
    assert {"tasks", "api_keys", "rate_buckets", "tags", "task_tags", "task_results"} <= _tables(db_url)

    result_downgrade_exit = migration_state.downgrade(db_url, "base")
    result_residual_tables = sorted(_tables(db_url) - {"alembic_version"})

    # AC7.2-upgrade
    assert result_upgrade_exit == int(expected_upgrade_exit)
    # AC7.2-downgrade
    assert result_downgrade_exit == int(expected_downgrade_exit)
    # AC7.2-clean
    assert len(result_residual_tables) == int(expected_residual_tables)
    assert migration_state.current_revision(db_url) is None


# --- 3 ---------------------------------------------------------------------


def test_fr07_roundtrip_sample_data_identical_per_column(db_url):
    db_backend = "sqlite-file"
    sample_rows = "3"
    sample_exit_code = "7"
    sample_stdout_tail = "line one"
    sample_stderr_tail = "warn"
    sample_duration_ms = "1234"
    sample_finished_at = "2026-01-02T03:04:05"

    assert migration_state.upgrade(db_url, "head") == 0
    tasks = _insert_tasks(db_url, int(sample_rows), "rt")
    before = _insert_results(
        db_url,
        [t[0] for t in tasks],
        [
            (int(sample_exit_code), sample_stdout_tail, sample_stderr_tail, int(sample_duration_ms), sample_finished_at)
            for _ in tasks
        ],
    )

    assert migration_state.downgrade(db_url, "-1") == 0
    assert migration_state.current_revision(db_url) == "v2"
    assert "task_results" not in _tables(db_url)
    assert "result_json" in _columns(db_url, "tasks")
    with _connect(db_url) as conn:
        moved = conn.execute("SELECT COUNT(*) FROM tasks WHERE result_json IS NOT NULL").fetchone()[0]
    assert moved == int(sample_rows)

    assert migration_state.upgrade(db_url, "head") == 0
    assert "result_json" not in _columns(db_url, "tasks")
    after = _select_results(db_url)

    result_mismatched_columns = _mismatched_columns(before, after)
    result_row_count_after = len(after)
    result_db_backend = _backend(db_url)

    # AC7.3-columns
    assert len(result_mismatched_columns) == 0
    # AC7.3-rows
    assert result_row_count_after == int(sample_rows)
    # AC7.1-backend
    assert result_db_backend == db_backend
    assert _select_tasks(db_url) == sorted(tasks, key=lambda r: r[2])


# --- 4 ---------------------------------------------------------------------


def test_fr07_downgrade_is_real_not_drop_shortcut(db_url):
    db_backend = "sqlite-file"
    sample_rows = "3"
    expected_rows_lost = "0"
    expected_drop_shortcut_hits = "0"
    scan_root = "migrations/versions"

    files = sorted(p for p in (SRC_ROOT / scan_root).glob("*.py") if p.name != "__init__.py")
    assert len(files) == 3
    result_drop_shortcut_hits = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and DROP_SHORTCUT.search(node.value):
                result_drop_shortcut_hits.append(f"{path.name}:{node.lineno}")

    assert migration_state.upgrade(db_url, "head") == 0
    tasks = _insert_tasks(db_url, int(sample_rows), "real")
    _insert_results(db_url, [t[0] for t in tasks], [(0, "out", "", 10, "2026-01-02T03:04:05") for _ in tasks])

    assert migration_state.downgrade(db_url, "v2") == 0
    with _connect(db_url) as conn:
        carried = conn.execute("SELECT COUNT(*) FROM tasks WHERE result_json IS NOT NULL").fetchone()[0]
    result_rows_lost = int(sample_rows) - carried
    result_db_backend = _backend(db_url)

    # AC7.4-no-loss
    assert result_rows_lost == int(expected_rows_lost)
    # AC7.4-no-shortcut
    assert len(result_drop_shortcut_hits) == int(expected_drop_shortcut_hits)
    # AC7.1-backend
    assert result_db_backend == db_backend
    assert _select_tasks(db_url) == sorted(tasks, key=lambda r: r[2])


# --- 5 ---------------------------------------------------------------------


def test_fr07_offline_sql_generation(tmp_path):
    revisions = "v1,v2,v3"
    expected_tokens = "CREATE TABLE tasks,CREATE TABLE api_keys,CREATE TABLE task_results"
    url = f"sqlite:///{tmp_path / 'offline.db'}"

    result_offline_sql = migration_state.offline_sql(url, "base", "head")

    # offline mode never connects: no DB file may appear
    assert not (tmp_path / "offline.db").exists()
    # AC7.5-sql
    assert all(tok in result_offline_sql for tok in expected_tokens.split(","))
    for rev in revisions.split(","):
        assert f"'{rev}'" in result_offline_sql
    assert "CREATE TABLE tags" in result_offline_sql
    assert "CREATE TABLE task_tags" in result_offline_sql
    assert re.search(r"CREATE UNIQUE INDEX \S+ ON tasks \(name\)", result_offline_sql)


# --- 6 ---------------------------------------------------------------------


def test_fr07_v2_unique_name_index_rejects_duplicate(db_url):
    duplicate_name = "dup-1"

    assert migration_state.upgrade(db_url, "v2") == 0
    assert migration_state.current_revision(db_url) == "v2"
    with _connect(db_url) as conn:
        conn.execute(
            "INSERT INTO tasks (id, command, name, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), "echo a", duplicate_name, "pending", "2026-01-01T00:00:00"),
        )
    result_duplicate_rejected = False
    try:
        with _connect(db_url) as conn:
            conn.execute(
                "INSERT INTO tasks (id, command, name, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), "echo b", duplicate_name, "pending", "2026-01-01T00:00:01"),
            )
    except sqlite3.IntegrityError:
        result_duplicate_rejected = True

    # AC7.1-dup
    assert result_duplicate_rejected
    with _connect(db_url) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks WHERE name = ?", (duplicate_name,)).fetchone()[0] == 1


# --- 7 ---------------------------------------------------------------------


def test_fr07_v2_downgrade_preserves_v1_data(db_url):
    sample_rows = "3"
    expected_rows_lost = "0"

    assert migration_state.upgrade(db_url, "v1") == 0
    tasks = _insert_tasks(db_url, int(sample_rows), "v1")
    with _connect(db_url) as conn:
        conn.execute(
            "INSERT INTO api_keys (id, key_hash, scope, created_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), "a" * 64, "admin", "2026-01-01T00:00:00"),
        )
        conn.execute(
            "UPDATE tasks SET result_json = ? WHERE name = ?", ('{"exit_code": 0}', tasks[0][2])
        )

    assert migration_state.upgrade(db_url, "v2") == 0
    with _connect(db_url) as conn:
        tag_id = str(uuid.uuid4())
        conn.execute("INSERT INTO tags (id, label) VALUES (?, ?)", (tag_id, "nightly"))
        conn.execute("INSERT INTO task_tags (task_id, tag_id) VALUES (?, ?)", (tasks[0][0], tag_id))

    assert migration_state.downgrade(db_url, "v1") == 0
    assert migration_state.current_revision(db_url) == "v1"
    remaining = _select_tasks(db_url)
    result_rows_lost = int(sample_rows) - len(remaining)

    # AC7.4-no-loss
    assert result_rows_lost == int(expected_rows_lost)
    assert remaining == sorted(tasks, key=lambda r: r[2])
    assert not {"tags", "task_tags"} & _tables(db_url)
    with _connect(db_url) as conn:
        assert conn.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0] == 1
        assert conn.execute(
            "SELECT result_json FROM tasks WHERE name = ?", (tasks[0][2],)
        ).fetchone()[0] == '{"exit_code": 0}'
        unique_name_indexes = [
            idx[1]
            for idx in conn.execute("PRAGMA index_list(tasks)").fetchall()
            if idx[2] == 1
            and [c[2] for c in conn.execute(f"PRAGMA index_info('{idx[1]}')").fetchall()] == ["name"]
        ]
    assert unique_name_indexes == []


# --- 8 ---------------------------------------------------------------------


def test_sec_t09_v3_roundtrip_preserves_data(db_url):
    sample_rows = "5"
    expected_rows_lost = "0"

    assert migration_state.upgrade(db_url, "head") == 0
    tasks = _insert_tasks(db_url, int(sample_rows), "t09")
    # Adversarial payloads: NULLs, quotes, JSON-looking text, unicode, empty strings.
    values = [
        (0, "ok", "", 1, "2026-01-02T03:04:05"),
        (None, None, None, None, None),
        (-9, 'he said "hi"\n{"x": 1}', "back\\slash 'quote'", 2**31, "2026-12-31T23:59:59"),
        (127, "中文 輸出 ✓", "\t\r\n", 0, "2026-06-15T12:00:00.123456"),
        (1, "x" * 4096, "err", 999999, "2026-01-01T00:00:00"),
    ]
    before = _insert_results(db_url, [t[0] for t in tasks], values)

    assert migration_state.downgrade(db_url, "-1") == 0
    assert migration_state.upgrade(db_url, "head") == 0
    after = _select_results(db_url)

    result_mismatched_columns = _mismatched_columns(before, after)
    result_row_count_after = len(after)
    result_rows_lost = int(sample_rows) - result_row_count_after

    # AC7.3-columns
    assert len(result_mismatched_columns) == 0
    # AC7.3-rows
    assert result_row_count_after == int(sample_rows)
    # AC7.4-no-loss
    assert result_rows_lost == int(expected_rows_lost)
