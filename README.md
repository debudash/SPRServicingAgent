# SPR Servicing Desk (v2)

A multi-agent servicing desk for SPR Financials' SecureGrowth Fixed Annuity: withdrawals and hardship
cases handled by coordinated agents (Concierge, Knowledge, Transaction, Compliance, Case) with a human
reviewer for the highest-risk actions. Built through a repeatable pipeline: every change is an issue,
a branch, a PR and a set of gates, whether a person or an agent wrote it.

- **Brief:** [problemstmt/AI_Engineer_Assignment.docx](problemstmt/AI_Engineer_Assignment.docx)
- **v1 (single agent, frozen):** [baseline/](baseline/README.md), released as
  [v1.0](https://github.com/debudash/SPRServicingAgent/releases/tag/Agent-V1-SPRF-final)

> Status: B0 (foundation and framing). Built in tracer bullets: see [docs/PLAN.md](docs/PLAN.md) and
> [ADR 0001](docs/decisions/0001-tracer-bullets-over-layered-milestones.md). No v2 agents exist yet.

## Layout

| Folder | What it is | Owner |
|---|---|---|
| `contracts/` | Typed interfaces between lanes | integrator |
| `data/` | Store, data contract, synthetic data, ingestion, audit store | `data` lane (Dev A) |
| `agents/` | The runtime agents, orchestration, tools, UI | `agents` lane (Dev B) |
| `evals/`, `redteam/` | Eval harness, attack library | `quality` lane (Dev A) |
| `evals/golden/` | Answer key and thresholds | integrator |
| `docs/` | Blueprint, decisions (ADRs), issue log | integrator |
| `baseline/` | v1, frozen | integrator |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
make check                        # lint, types, tests: the same as CI
docker compose run --build --rm checks    # the same, inside the container
```

## How the build runs

- **Gates on every PR (no API cost):** `test` (lint, types, unit and contract tests) and, for agent PRs,
  `verdict` (an independent Claude review). Both are required to merge.
- **Night shift:** unattended Claude Code agents, one per lane, pick `night-safe` issues, build them and
  open PRs. Kill switch: repo variable `AGENTS_ENABLED`. See [RUNBOOK.md](RUNBOOK.md) and
  [AGENT_RULES.md](AGENT_RULES.md).
- **Paid evals:** run by hand at milestones through the `evals` workflow, not on every PR.
