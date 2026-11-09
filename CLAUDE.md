# CLAUDE.md

Rules for every agent and human working in this repo. Agents cannot edit this file; humans change it by PR.

## Product
v2 of the SPR Financials servicing agent: a multi-agent **Withdrawal & Hardship Case Desk** for the
SecureGrowth Fixed Annuity. The brief is `problemstmt/AI_Engineer_Assignment.docx`; the provided data is
`problemstmt/spr_starter_kit/`. v1 (one tool-calling agent) is frozen in `baseline/` and is the
single-agent baseline v2 is compared against. Design lives in `docs/` (blueprint, `docs/decisions/`).

## Commands
Python 3.12. Install with `pip install -r requirements-dev.txt`. Run from the repo root.
- Before finishing any change: `make check` (ruff lint + format check, mypy strict, pytest). CI runs the same.
- Format: `make fmt`
- In Docker (same image CI builds): `docker compose run --rm checks`
- v1 baseline: `cd baseline && python -m scripts.smoke_test`

## Agent coordination
See AGENT_RULES.md: lanes and ownership, one issue = one branch = one PR, never push to main, never edit
integrator paths (`.github/`, `contracts/`, `evals/golden/`, `baseline/`, `CLAUDE.md`, ...), and write one
line to a new file `progress/<lane>/<YYYY-MM-DD>-issue-<n>.md` per change.

## Project rules
- **Numbers come from records, narrative from documents.** Balances, charges and allowances come from the
  data store and calculation code, never from the knowledge base or the model.
- **Restricted fields never reach a model.** Date of birth and SSN digits stay inside the identity code:
  never in prompts, traces, logs or answers.
- **Guards live in code.** Identity gates, quote-before-execute, approval tokens and budgets are enforced
  in code and unit-tested. Prompts explain the rules; they are not the safety layer.
- **No teaching to the test.** Fix the behaviour, not the eval case. Never weaken, skip or delete a test
  to make a change pass. The golden eval set (`evals/golden/`) is human-owned.
- **Tests make no network calls.** Unit tests use fakes or recorded model responses. Paid LLM evals run
  only through the manual `evals` workflow.
- **Every served component runs in Docker** (`compose.yaml`), never as a bare host process.

## Review (who reviews what)
Full table in AGENT_RULES.md; reasons in `docs/decisions/0002-two-axis-review.md`.
- Agent PRs: the automatic `verdict` review is the gate.
- Human PRs that touch `contracts/`, `evals/golden/` or the money path (quote, execute, approvals, rule
  engine, Compliance, human approval, identity gates): run `/code-review` before merge and post its
  findings as a PR comment. Money-path agent PRs get the same spot-check.
- Every PR fills in "Reviewed by" in the PR template, with the reason when no review is required.
- A real defect found in review becomes a bug issue and follows "Fixing a bug" below.

## Fixing a bug
1. Open (or use) an issue in the bug format: Issue, Root cause, Fix, Test.
2. Write a failing test that reproduces it first. Name the issue ID in the test and add a one-line
   "found by" note.
3. Fix it, with a short comment at the fix site: issue ID, root cause, why the fix works.
4. Commit message has four labelled parts: `Issue:`, `Root cause:`, `Fix:`, `Test:`. One issue per commit.
5. Add a row to `docs/ISSUE_LOG.md` (the commit hash can follow in the next PR).
