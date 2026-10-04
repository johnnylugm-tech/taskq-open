# NFR-12: end-to-end system verification target.
PYTHON ?= $(if $(wildcard $(CURDIR)/.venv/bin/python),$(CURDIR)/.venv/bin/python,python3)

.PHONY: verify-system
verify-system:
	@set -e; \
	work=$$(mktemp -d); \
	trap 'rm -rf "$$work"' EXIT; \
	export TASKQ_DB_URL="sqlite:///$$work/taskq.db"; \
	echo "verify-system: 1/4 alembic upgrade head"; \
	( cd "$$work" && $(PYTHON) -m alembic -c "$(CURDIR)/alembic.ini" upgrade head ); \
	echo "verify-system: 2/4 full test suite"; \
	$(PYTHON) -m pytest "$(CURDIR)/03-development/tests" -q; \
	echo "verify-system: 3/4 service smoke (/healthz, /readyz, key create, task run)"; \
	smoke_key=$$(PYTHONPATH="$(CURDIR)/03-development/src" $(PYTHON) -m taskq_api key create --scope write); \
	TASKQ_SMOKE_KEY="$$smoke_key" $(PYTHON) "$(CURDIR)/scripts/smoke_probe.py"; \
	echo "verify-system: 4/4 alembic downgrade base, upgrade head"; \
	( cd "$$work" && $(PYTHON) -m alembic -c "$(CURDIR)/alembic.ini" downgrade base \
		&& $(PYTHON) -m alembic -c "$(CURDIR)/alembic.ini" upgrade head ); \
	echo "verify-system: PASS"
