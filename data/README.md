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

## Demo logins (ADR 0007)

The login page stands in for upstream authentication. The starter customers' demo passwords are in
`data/demo_logins.json` (synthetic, labelled), and the seed stores only salted scrypt hashes in the
`logins` table, which only `data/identity.py` may read.

| Customer | Password | What the demo shows |
|---|---|---|
| SPR-1001 Margaret Holloway | `margaret-demo` | Trusted: account view, quotes, the money path |
| SPR-1002 Raymond Okafor | `raymond-demo` | Logs in, but the account is untrusted (Gate A): turned away |
| SPR-1003 Linda Chu | `linda-demo` | Trusted, under 59 1/2: the IRS notice |
| SPR-1004 Thomas Brennan | `thomas-demo` | Trusted, contract year 5 (3%, not 4%) |
