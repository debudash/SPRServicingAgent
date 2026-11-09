# data lane

The data lane owns everything about how records are stored and fed to the rest of the system: the
relational store, the data contract, the synthetic data, ingestion, and the audit store. Other lanes
read this data through the contract and never reach around it.

## Rule

**Numbers come from records, narrative from documents.** Balances, charges and allowances come from the
data store and calculation code, never from the knowledge base or the model.

## What this lane does NOT own

- `contracts/` (interfaces, stubs and contract tests): integrator only.
- `evals/golden/` (the golden eval set): human-owned.

See `AGENT_RULES.md` and `CLAUDE.md` for the full ownership table.
