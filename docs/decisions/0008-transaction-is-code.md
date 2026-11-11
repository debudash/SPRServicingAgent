# 0008. The Transaction step is code, not a model

Date: 2026-11-10 · Status: accepted · Decided by: integrator (owner) · Issue: #88 (PR #129)

Amends ADR 0004: the Transaction row of the model map is not used.

## Context
ADR 0004 and ARCHITECTURE 3.3 gave the Transaction role a model (Sonnet 5.5, medium effort), with the
tools `get_account`, `quote` and `propose`. When #88 built it, nothing was left for that model to decide:

- The Concierge already extracts the amount (`Intent.amount_cents`), and routing (code, ADR 0003) decides
  whether a stated amount is a new quote or an answer to the live one.
- Every figure must come from the quote service and be formatted by code (GR-02), so the model may not
  write the reply's numbers.
- The tool order is fixed: read the account, quote, save the proposal. A refused quote saves nothing.

A model here would add a call per quote (cost, latency and one more non-deterministic step on the money
path) without changing any outcome.

## Decision
- The `transaction` node is code. It calls its three tools through the tool registry under
  `Role.TRANSACTION`, so the tool scope (FR-22) is enforced exactly as it would be for a model.
- The Transaction row stays in `agents/config/models.yaml`, unused, so a model can be put in front of the
  same tools later without changing the guards (for example, to handle a request that names no clear
  amount).
- The model comparison (ADR 0004) runs on the roles that use a model: Concierge, Knowledge, Compliance and
  Case. That is still at least two roles, as the brief asks.

## Consequences
- One model call fewer per quote, and the quote turn is deterministic after the Concierge.
- ARCHITECTURE 3.3 and the blueprint name the Transaction step as code.
- If evals show customers phrasing withdrawals the Concierge cannot extract, the fix is a model in front
  of the same tools, recorded as a new ADR.

## Alternatives rejected
- **Keep Sonnet as specified.** It would only restate code's decisions, at a cost per quote.
- **A model that writes the reply around code-formatted figures.** The reply texts are fixed and
  reviewed; a model there adds a place for advice (GR-08) or a wrong figure to slip in, for no gain.
