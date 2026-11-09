# 0001. Deliver in tracer bullets, not layered milestones

Date: 2026-11-09 · Status: accepted · Decided by: integrator (owner) · Issue: #8

## Context
The v2 brief first laid the build out as eight layered milestones: M0 framing, M1 data foundation,
M2 evals, M3 factory and first agents, M4 money path, M5 red team, M6 operate, M7 release. Each layer
was to be finished before the next began.

Built that way, nothing works end to end until M4. Integration problems surface late, at the riskiest
point (the maker–checker money path), the eval trend shows nothing until the agents exist, and there is
nothing to demonstrate until most of the time is spent.

## Decision
Deliver in **tracer bullets**: thin, complete customer paths cut through every layer at once
(contracts, data, agents, UI, trace, audit, eval cases), then thickened by the next bullet.

| Was (layers) | Now (bullets) |
|---|---|
| M0 Frame and blueprint | **B0** Foundation and framing |
| M1 Data foundation, M2 Define correct, M3 First agents | **B1** Cited product answer, **B2** Identity and account view |
| M4 Money path | **B3** Routine withdrawal, **B4** Human review path |
| (spread across M4–M6) | **B5** Hard cases and failure modes |
| M5 Red team, M6 Operate | **H** Hardening |
| M7 Release and evidence | **R** Release and evidence |

The bullets and the PRD items each one delivers are in `docs/PLAN.md`. GitHub milestones and `wave:<n>`
labels follow the bullets (B1 = `wave:1`, and so on).

## Consequences
- Each bullet is one night-shift wave with work in all three lanes. The integrator freezes that bullet's
  contracts first; `data`, `agents` and `quality` then build against them in parallel.
- The `quality` lane writes each bullet's eval cases alongside its features, so the eval trend starts at B1.
- The maker–checker path (B3) is built third instead of last, while there is still time to fix its design.
- Contracts grow bullet by bullet. Every `CONTRACTS_VERSION` bump must be additive: new fields and
  messages only, never changed or removed ones.
- The brief's milestone table is replaced by the bullet table, so the brief and the repo tell one story.

## Alternatives rejected
- **Keep layered milestones.** Simpler to plan, but integration risk lands at the end and there is
  nothing to show until M4.
- **Bullets without a hardening phase.** Red-team campaigns, model-per-role evals and the game day cut
  across every path, so they need their own phase after the paths exist.
