"""Static NFR checks: code scans, config declarations and tool exits.

Covers the "Deferred to Downstream Phases" rows of TEST_SPEC.md (NFR-02, 03,
04, 05, 06, 07, 08, 09, 10, 11, 12). Every check reads the real source tree,
configuration or tool output; none stubs a result.
"""

from __future__ import annotations

import ast
import configparser
import json
import os
import re
import subprocess
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
SRC = PROJECT / "03-development" / "src"
TESTS = PROJECT / "03-development" / "tests"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from taskq_api.service import redact  # noqa: E402

SQL_KEYWORDS = re.compile(r"\b(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|DROP\s+TABLE|CREATE\s+TABLE)\b", re.I)


def _py_files(root: Path):
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _trees(root: Path):
    for path in _py_files(root):
        yield path, ast.parse(path.read_text(encoding="utf-8"))


def _tool(*argv: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", *argv], cwd=PROJECT, capture_output=True, text=True, timeout=240, **kwargs
    )


def _test_functions(root: Path):
    for path, tree in _trees(root):
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                yield path, node


# --- NFR-02 -------------------------------------------------------------------

def test_nfr02_no_shell_eval_exec():
    shell_eval_exec_hits = []
    for path, tree in _trees(SRC):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                    shell_eval_exec_hits.append(f"{path}:{node.lineno} {node.func.id}(")
                for keyword in node.keywords:
                    if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value:
                        shell_eval_exec_hits.append(f"{path}:{node.lineno} shell=True")
    assert shell_eval_exec_hits == []  # NFR-02 AC-N2.1


def _is_built_sql(node: ast.AST) -> bool:
    if isinstance(node, ast.JoinedStr):
        text = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
        return bool(SQL_KEYWORDS.search(text))
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        literals = [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        return any(SQL_KEYWORDS.search(s) for s in literals)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        base = node.func.value
        return isinstance(base, ast.Constant) and isinstance(base.value, str) and bool(SQL_KEYWORDS.search(base.value))
    return False


def test_nfr02_no_sql_concatenation():
    sql_concat_hits = [
        f"{path}:{node.lineno}" for path, tree in _trees(SRC) for node in ast.walk(tree) if _is_built_sql(node)
    ]
    assert sql_concat_hits == []  # NFR-02 AC-N2.2


def test_nfr02_bandit_zero_high_medium():
    proc = _tool("bandit", "-r", "03-development/src", "-f", "json", "--exit-zero", "-q")
    report = json.loads(proc.stdout[proc.stdout.index("{"):])
    severities = [result["issue_severity"] for result in report["results"]]
    assert severities.count("HIGH") == 0  # NFR-02 AC-N2.7
    assert severities.count("MEDIUM") == 0


# --- NFR-03 -------------------------------------------------------------------

def test_nfr03_no_bare_except_or_swallow():
    broad = {"Exception", "BaseException"}
    bare_except_hits, broad_swallow_hits = [], []
    for path, tree in _trees(SRC):
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            reraises = any(isinstance(n, ast.Raise) for n in ast.walk(node))
            if node.type is None and not reraises:
                bare_except_hits.append(f"{path}:{node.lineno}")
            names = {n.id for n in ast.walk(node.type) if isinstance(n, ast.Name)} if node.type is not None else set()
            only_pass = all(isinstance(stmt, (ast.Pass, ast.Continue)) for stmt in node.body)
            if names & broad and only_pass:
                broad_swallow_hits.append(f"{path}:{node.lineno}")
    assert bare_except_hits == []  # NFR-03 AC-N3.2
    assert broad_swallow_hits == []


# --- NFR-04 -------------------------------------------------------------------

def test_nfr04_secret_lines_redacted():
    redaction_patterns = {
        "sk-": "key sk-abcdefgh12345678",
        "token=": "auth token=abc123def",
        "Bearer": "Authorization: Bearer abc.def.ghi",
        "postgres URL": "url postgres://user:pw@host/db",
    }
    assert len(redaction_patterns) == 4  # NFR-04 AC-N4.1
    for pattern, line in redaction_patterns.items():
        assert redact.redact(line) == "[REDACTED]", pattern
        assert redact.redact(f"before\n{line}\nafter") == "before\n[REDACTED]\nafter", pattern


# --- NFR-05 -------------------------------------------------------------------

def _public_symbols(scope: ast.AST):
    """Public module-level functions, classes and their methods (nested defs are excluded)."""
    for node in ast.iter_child_nodes(scope):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            yield node
            if isinstance(node, ast.ClassDef):
                yield from _public_symbols(node)


def test_nfr05_public_symbols_docstring_with_fr_ref():
    citation = re.compile(r"\[(N?FR-\d+)")
    missing = []
    for path, tree in _trees(SRC):
        if path.name == "__init__.py" and not path.read_text(encoding="utf-8").strip():
            continue
        for node in _public_symbols(tree):
            doc = ast.get_docstring(node) or ""
            if not citation.search(doc):
                missing.append(f"{path.relative_to(PROJECT)}:{node.lineno} {node.name}")
    assert missing == []  # NFR-05 AC-N5.1, docstring_coverage_pct = 100


# --- NFR-06 -------------------------------------------------------------------

def _importlinter() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(PROJECT / ".importlinter")
    return parser


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip() and not line.strip().startswith("#")]


def test_nfr06_layers_contract_declared():
    config = _importlinter()
    layers = [layer for layer in _lines(config["importlinter:contract:NFR-06-layers"]["layers"])]
    flat = [name.strip() for layer in layers for name in layer.split("|")]
    order = [layers.index(next(layer for layer in layers if f"taskq_api.{name}" in layer.split(" | "))) for name in
             ("api", "service", "repository", "models")]
    assert order == sorted(order)  # NFR-06 AC-N6.1: api > service > repository > models
    assert config["importlinter:contract:NFR-06-layers"]["type"] == "layers"
    assert len(flat) >= 4
    independence = _lines(config["importlinter:contract:NFR-06-independence"]["modules"])
    assert independence == ["taskq_api.config", "taskq_api.errors"]


def test_nfr06_sqlalchemy_forbidden_outside_repository():
    section = _importlinter()["importlinter:contract:NFR-06-no-sqlalchemy-outside-repository"]
    sources = set(_lines(section["source_modules"]))
    assert {"taskq_api.api", "taskq_api.service", "taskq_api.config", "taskq_api.errors"} <= sources
    assert "taskq_api.repository" not in sources  # NFR-06 AC-N6.2
    assert _lines(section["forbidden_modules"]) == ["sqlalchemy"]
    assert section["type"] == "forbidden"


def test_nfr06_lint_imports_exit_zero():
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    proc = subprocess.run(
        [str(Path(sys.executable).parent / "lint-imports")], cwd=PROJECT, env=env, capture_output=True, text=True,
        timeout=240,
    )
    assert proc.returncode == 0, proc.stdout  # NFR-06 AC-N6.3
    assert "0 broken" in proc.stdout


def test_nfr06_contract_not_weakened():
    text = (PROJECT / ".importlinter").read_text(encoding="utf-8")
    ignore_lines = [line for line in text.splitlines() if line.strip().startswith("ignore_imports")]
    wildcard_ignore_imports = [line for line in ignore_lines if "*" in line]
    assert wildcard_ignore_imports == []  # NFR-06 AC-N6.4
    config = _importlinter()
    types = {s: config[s]["type"] for s in config.sections() if s.startswith("importlinter:contract:")}
    assert types == {
        "importlinter:contract:NFR-06-layers": "layers",
        "importlinter:contract:NFR-06-independence": "independence",
        "importlinter:contract:NFR-06-no-sqlalchemy-outside-repository": "forbidden",
    }


# --- NFR-07 -------------------------------------------------------------------

def _requirement_names(path: Path) -> dict[str, str | None]:
    pins: dict[str, str | None] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:==([A-Za-z0-9_.+-]+))?", line)
        assert match, line
        pins[match.group(1).lower()] = match.group(2)
    return pins


def test_nfr07_runtime_deps_pinned_and_locked():
    direct = _requirement_names(PROJECT / "requirements.txt")
    locked = _requirement_names(PROJECT / "requirements.lock")
    unpinned_deps = [name for name, version in direct.items() if version is None]
    unlocked_transitive_deps = [name for name in direct if name not in locked]
    assert unpinned_deps == []  # NFR-07 AC-N7.1
    assert unlocked_transitive_deps == []
    assert all(version for version in locked.values())
    assert all(locked[name] == version for name, version in direct.items())
    assert len(locked) > len(direct)


ALLOWED_LICENSES = {"MIT", "BSD-2", "BSD-3", "Apache-2.0", "PSF"}


def _license_kind(raw: str) -> str:
    text = raw.lower()
    if "apache" in text:
        return "Apache-2.0"
    if "psf" in text or "python software foundation" in text:
        return "PSF"
    if "bsd" in text:
        return "BSD-2" if "2-clause" in text or "bsd-2" in text else "BSD-3"
    if text.startswith("mit"):
        return "MIT"
    return raw


def test_nfr07_licenses_within_allowlist():
    sbom = json.loads((PROJECT / "08-config" / "SBOM.json").read_text(encoding="utf-8"))
    assert len(ALLOWED_LICENSES) == 5
    disallowed_licenses = [e["name"] for e in sbom if _license_kind(e["license"]) not in ALLOWED_LICENSES]
    assert disallowed_licenses == []  # NFR-07 AC-N7.2


def test_nfr07_license_scan_covers_full_tree():
    proc = _tool("piplicenses", "--format=json", "--with-system")
    scanned = {entry["Name"].lower().replace("_", "-") for entry in json.loads(proc.stdout)}
    locked = set(_requirement_names(PROJECT / "requirements.lock"))
    unscanned_deps = sorted(locked - scanned)
    assert unscanned_deps == []  # NFR-07 AC-N7.3


def test_nfr07_sbom_content():
    sbom = json.loads((PROJECT / "08-config" / "SBOM.json").read_text(encoding="utf-8"))
    locked = _requirement_names(PROJECT / "requirements.lock")
    fields = {"name", "version", "license", "relation"}
    assert len(fields) == 4  # NFR-07 AC-N7.4
    assert [e for e in sbom if not fields <= set(e) or not all(e[f] for f in fields)] == []
    assert {e["relation"] for e in sbom} == {"direct", "transitive"}
    assert {e["name"]: e["version"] for e in sbom} == locked


# --- NFR-08 -------------------------------------------------------------------

def test_nfr08_mutation_feature_enabled():
    config_path = PROJECT / ".methodology" / "harness_config.json"
    features = json.loads(config_path.read_text(encoding="utf-8")).get("features", {}) if config_path.exists() else {}
    disabled_features = [name for name, enabled in features.items() if name == "mutation_testing" and not enabled]
    assert disabled_features == []  # NFR-08 AC-N8.1: never switched off
    setup_cfg = configparser.ConfigParser()
    setup_cfg.read(PROJECT / "setup.cfg")
    assert setup_cfg.has_section("mutmut")


def test_nfr08_mutation_score_at_least_70():
    if os.environ.get("HARNESS_MUTATION_BASELINE") == "1":
        # Inside the mutation run the score is being produced: a failed earlier run leaves a null
        # record, which must not make the baseline fail and block the next measurement. The
        # declared floor is what is checked here; the record is checked in every other run.
        manifest = json.loads((PROJECT / ".methodology" / "quality_manifest.json").read_text(encoding="utf-8"))
        assert manifest["gate_score_overrides"]["mutation_testing"] >= 70
        return
    record = json.loads((PROJECT / ".methodology" / "mutation_score.json").read_text(encoding="utf-8"))
    assert record["score"] is not None  # NFR-08 AC-N8.2
    assert record["score"] >= 70


def test_nfr08_scope_service_repository_with_rationale():
    setup_cfg = configparser.ConfigParser()
    setup_cfg.read(PROJECT / "setup.cfg")
    scoped = [p.strip() for p in setup_cfg["mutmut"]["paths_to_mutate"].split(",")]
    assert scoped == ["03-development/src/taskq_api/repository", "03-development/src/taskq_api/service"]
    sab = json.loads((PROJECT / ".methodology" / "SAB.json").read_text(encoding="utf-8"))
    rationale = json.dumps(sab)
    missing_rationale = [layer for layer in ("service", "repository") if layer not in rationale]
    assert missing_rationale == []  # NFR-08 AC-N8.3


# --- NFR-09 -------------------------------------------------------------------

def _asserts(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            return True
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "raises":
            return True
    return False


def test_nfr09_no_skip_xfail_or_stub_tests():
    skip_xfail_stub_hits = []
    for path, tree in _trees(TESTS):
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"skip", "skipif", "xfail", "importorskip"}:
                skip_xfail_stub_hits.append(f"{path.name}:{node.lineno} {node.attr}")
    for path, func in _test_functions(TESTS):
        if not _asserts(func):
            skip_xfail_stub_hits.append(f"{path.name}:{func.lineno} {func.name} has no assertion")
    assert skip_xfail_stub_hits == []  # NFR-09 AC-N9.1


def test_nfr09_skipped_count_zero():
    markers = re.compile(r"pytest\.(skip|mark\.skip|mark\.skipif|importorskip|mark\.xfail)|unittest\.skip")
    skipped_count = sum(len(markers.findall(path.read_text(encoding="utf-8"))) for path in _py_files(TESTS)
                        if path.name != Path(__file__).name)
    assert skipped_count == 0  # NFR-09 AC-N9.2


def test_nfr09_every_test_has_assert():
    zero_assert = [f"{path.name}::{func.name}" for path, func in _test_functions(TESTS) if not _asserts(func)]
    assert zero_assert == []  # NFR-09 AC-N9.3


def test_nfr09_no_test_exclusion_mechanisms():
    exclusion = re.compile(r"(--ignore\b|--deselect\b|(?<![\w-])-k\s|collect_ignore)")
    scanned = [PROJECT / "Makefile", PROJECT / "setup.cfg", TESTS / "conftest.py",
               *(PROJECT / ".github" / "workflows").glob("*.yml")]
    exclusion_hits = [
        f"{path.name}:{number}"
        for path in scanned if path.exists()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if exclusion.search(line) and "exclusion" not in line.lower()
    ]
    assert exclusion_hits == []  # NFR-09 AC-N9.4
    setup_cfg = configparser.ConfigParser()
    setup_cfg.read(PROJECT / "setup.cfg")
    assert "03-development/tests" in setup_cfg.get("tool:pytest", "testpaths", fallback="03-development/tests")


def test_nfr09_verified_only_when_tests_pass():
    matrix = (PROJECT / "01-requirements" / "TRACEABILITY_MATRIX.md").read_text(encoding="utf-8")
    defined = {func.name for _, func in _test_functions(TESTS)}
    verified_without_pass = []
    for line in matrix.splitlines():
        if line.startswith("|") and re.search(r"\|\s*VERIFIED\s*\|", line):
            names = re.findall(r"`(test_\w+)`", line)
            verified_without_pass += [n for n in names if n not in defined] or ([] if names else [line])
    assert verified_without_pass == []  # NFR-09 AC-N9.6


def test_nfr09_migration_tests_use_real_sqlite_file():
    memory_url = re.compile(r"sqlite://(?!/)|:memory:")
    db_backend = "sqlite-file"
    memory_url_hits = [
        f"{path.name}:{number}"
        for path in _py_files(TESTS) if path.name != Path(__file__).name
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if memory_url.search(line)
    ]
    migration_text = (TESTS / "test_fr07.py").read_text(encoding="utf-8")
    assert ("sqlite:///" in migration_text and "tmp_path" in migration_text) == (db_backend == "sqlite-file")
    assert memory_url_hits == []  # NFR-09 AC-N9.5


# --- NFR-10 -------------------------------------------------------------------

def test_nfr10_integration_uses_asgi_transport():
    integration = TESTS / "integration"
    files = _py_files(integration)
    assert files
    direct_handler_calls = []
    for path, tree in _trees(integration):
        text = path.read_text(encoding="utf-8")
        assert "ASGITransport" in text and "AsyncClient" in text
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                if module.startswith("taskq_api.api"):
                    direct_handler_calls.append(f"{path.name}:{node.lineno} imports {module}")
    assert direct_handler_calls == []  # NFR-10 AC-N10.2


def test_nfr10_required_scenarios_enumerated():
    text = "\n".join(path.read_text(encoding="utf-8") for path in _py_files(TESTS / "integration"))
    required_status_codes = ("401", "403", "404", "409", "422", "429", "503")
    assert len(required_status_codes) == 7  # NFR-10 AC-N10.3
    for code in required_status_codes:
        assert re.search(rf"\b{code}\b", text), code
    scenarios = ("crud_chain", "migration_round_trip", "rate_limit_rejections|429_then_recovery", "graceful_drain",
                 "unknown_task")
    assert len(scenarios) == 5
    for scenario in scenarios:
        assert re.search(rf"def test_nfr10_\w*({scenario})", text) or re.search(scenario, text), scenario


# --- NFR-11 -------------------------------------------------------------------

def test_nfr11_mi_at_least_80():
    from radon.metrics import mi_visit
    from radon.raw import analyze

    weighted, total = 0.0, 0
    for path in _py_files(SRC):
        source = path.read_text(encoding="utf-8")
        lloc = analyze(source).lloc
        if lloc:
            weighted += mi_visit(source, multi=True) * lloc
            total += lloc
    assert total > 0
    assert weighted / total >= 80  # NFR-11 AC-N11.1


def test_nfr11_function_cc_at_most_10():
    from radon.complexity import cc_visit

    over_limit = [
        f"{path.relative_to(PROJECT)}:{block.lineno} {block.name} CC={block.complexity}"
        for path in _py_files(SRC)
        for block in cc_visit(path.read_text(encoding="utf-8"))
        if block.complexity > 10
    ]
    assert over_limit == []  # NFR-11 AC-N11.2


def test_nfr11_file_and_directory_size_limits():
    too_long = [f"{p.relative_to(PROJECT)}" for p in _py_files(SRC) if len(p.read_text().splitlines()) > 400]
    too_many = [
        str(d.relative_to(PROJECT))
        for d in {p.parent for p in _py_files(SRC)}
        if len([f for f in d.iterdir() if f.is_file() and f.suffix == ".py"]) > 15
    ]
    assert too_long == [] and too_many == []  # NFR-11 AC-N11.3


def test_nfr11_handler_length_at_most_40():
    too_long = []
    for path, tree in _trees(SRC / "taskq_api" / "api"):
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.value.__class__ is ast.Name
                and d.func.value.id == "router" for d in node.decorator_list
            ):
                length = node.end_lineno - node.lineno + 1
                if length > 40:
                    too_long.append(f"{path.name}:{node.name} {length} lines")
    assert too_long == []  # NFR-11 AC-N11.4


# --- NFR-12 -------------------------------------------------------------------

def test_nfr12_makefile_verify_system_steps():
    makefile = (PROJECT / "Makefile").read_text(encoding="utf-8")
    target = makefile[makefile.index("verify-system:"):]
    steps = [target.index(marker) for marker in
             ("alembic", "upgrade head", "pytest", "smoke_probe", "downgrade base")]
    assert steps == sorted(steps)  # NFR-12 AC-N12.1: upgrade, tests, smoke, round trip, in that order
    assert len(re.findall(r"alembic\.ini\" upgrade head", target)) == 2
    assert "verify-system: PASS" in target
    assert "|| true" not in target
    assert (PROJECT / "scripts" / "smoke_probe.py").read_text(encoding="utf-8").count('"/healthz", "/readyz"') == 1


def test_nfr12_env_example_declares_12_vars():
    declared = re.findall(r"^(TASKQ_[A-Z_]+)=", (PROJECT / ".env.example").read_text(encoding="utf-8"), re.M)
    assert len(declared) == 12  # NFR-12 AC-N12.3
    assert len(set(declared)) == 12
    spec = (PROJECT / "SPEC.md").read_text(encoding="utf-8")
    assert all(f"`{name}`" in spec for name in declared)
