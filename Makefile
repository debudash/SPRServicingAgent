# One set of commands for humans, agents and CI. `make check` is what the `test` CI check runs.
# Owned by the integrator; tickets name these targets, lanes build the modules behind them.
PY ?= python
PACKAGES = contracts data agents evals redteam

.PHONY: check lint type test fmt picker-test ingest desk evals

check: lint type test

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

type:
	$(PY) -m mypy $(PACKAGES)

test:
	$(PY) -m pytest

fmt:
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

picker-test:
	$(PY) -m unittest discover -s .github/night-shift/tests

# Build the knowledge index from knowledge/ into var/chroma (data lane, B1).
ingest:
	$(PY) -m data.knowledge_index.ingest

# Run the desk in Docker at http://localhost:8530 (agents lane, B1).
desk:
	docker compose up --build desk

# Paid LLM evals, by hand only (quality lane, B1). Example: make evals ARGS="--suite golden --bullet B1"
evals:
	$(PY) -m evals.run $(ARGS)
