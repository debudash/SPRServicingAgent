# 0004. A model per role, compared within Claude, judged by a non-Claude model

Date: 2026-11-09 · Status: accepted · Decided by: integrator (owner) · Issue: #15

Amended by ADR 0008 (2026-11-10): the Transaction step is code, so its row below is not used.

## Context
The cost model ([COST_MODEL.md](../COST_MODEL.md)) shows that Sonnet 5.5 on every agent costs about $0.104
per routine withdrawal without caching and $0.051 with it, both above the $0.042 target (PRD M-14), and the
uncached figure is above the $0.10 per-conversation budget (D-10). The Concierge makes most of the calls and needs
the least judgment. The brief asks for at least two models compared on at least two roles.

## Decision
- **Starting map:**

  | Role | Model | Effort |
  |---|---|---|
  | Concierge (and the `respond` step) | Claude Haiku 5.5 | low |
  | Case | Claude Haiku 5.5 | low |
  | Knowledge | Claude Sonnet 5.5 | medium |
  | Transaction | Claude Sonnet 5.5 | medium |
  | Compliance | Claude Sonnet 5.5 | high |

  Estimated cost with caching: about $0.014 per routine withdrawal.
- **Comparison scope: Claude only.** Haiku 5.5 vs Sonnet 5.5 per role, plus Opus 5.5 for Compliance. One
  API key, one SDK, one caching scheme.
- **The judge is not a contestant.** Where an LLM judge is needed (EVAL_SPEC §3), it is a non-Claude
  model through OpenRouter, as in v1, and it must agree with human labels at least 85% of the time first.
- **When it is decided:** the map is a starting point. The full eval run at the end of B3 confirms or
  changes it, and the H phase runs the formal comparison. A role moves to a stronger model only when its
  evals show the cheaper one failing a target.

## Consequences
- Model IDs live in one configuration file per role, so the comparison changes configuration, not code.
- Caches are per model, so each role keeps its own cache. That is already true with one system prompt per
  role, so the split costs nothing extra.
- The comparison says nothing about other providers. That is a deliberate scope cut, stated in the README.

## Alternatives rejected
- **Sonnet everywhere first.** A quality ceiling to start from, but it fails the cost target until the H
  phase, and every B1 to B5 eval would run at the higher cost.
- **Haiku everywhere except Compliance.** Cheapest, but Knowledge (citations) and Transaction (explaining
  money) are where quality matters next after Compliance.
- **Adding another provider, as v1 did.** Two more keys, provider-specific caching and more eval cost, for
  a comparison the brief does not require.
