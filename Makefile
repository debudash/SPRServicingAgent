# One set of commands for humans, agents and CI. `make check` is what the `test` CI check runs.
PY ?= python
PACKAGES = contracts data agents evals redteam

.PHONY: check lint type test fmt picker-test

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
