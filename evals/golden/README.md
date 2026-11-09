# Golden eval set (integrator-owned)

The answer key for the desk. Agent PRs that touch this folder are rejected by the pipeline: an agent must
never make a ticket pass by changing the answer key. Humans add and change cases here, by PR.

| File | What it holds |
|---|---|
| `golden.yaml` | One customer turn, one correct outcome. Graded without a judge. |
| `behavioural.yaml` | Multi-turn scenarios, graded on the trace (tools and their order) and the outcome. |
| `test_golden_set.py` | Checks the key itself: well-formed cases, every grounding rule pinned, PRD references exist, every expected quote recomputes from the starter data. Runs in `make check`. |

Unit-level checks (quote math, gates, token binding, idempotency, budgets, tool scope, the restricted-field
scrubber) are not evals. They are pytest tests in each lane, run with a scripted model. See
[docs/EVAL_SPEC.md](../../docs/EVAL_SPEC.md).

## Case fields

| Field | Meaning |
|---|---|
| `id` | `G-<bullet>-NN` (golden) or `BH-<bullet>-NN` (behavioural). Never reused. |
| `bullet` | The tracer bullet that must make it pass (`docs/PLAN.md`). Cases for later bullets are reported, not counted, until their bullet starts. |
| `rules` | Grounding rules it pins (`docs/GROUNDING_RULES.md`). |
| `prd` | PRD items it evidences. |
| `customer` | Starter or synthetic customer ID, or `null` for an anonymous product question. |
| `session.gate_b_passed` | Whether the identity challenge was already passed before this case. |
| `status` | `active` (default) or `pending_data` (its data does not exist yet; reported, not run). |
| `quote` | The exact expected quote. `threshold_tier` is the tier from the amount rules alone (D-02). |
| `faults` | Failures injected by the harness: `compliance_unavailable`, `tool_loop`, `execution_disabled`, `replay_last_execute`. |

## Expectations

| Key | Passes when |
|---|---|
| `outcome` / `final_outcome` | The trace's outcome code equals it (`ANSWERED`, `EXECUTED`, or a PRD §6 code). |
| `contains` / `not_contains` | Each string is / is not in the answer (case-insensitive). |
| `numbers` | Each money value appears exactly, after removing `$` and spaces. |
| `cites` / `cites_any` | The answer cites all of / at least one of these document IDs. |
| `cites_version: current` | Every citation names the version in force at the as-of date. |
| `tools` / `not_tools` | Each tool was / was not called. |
| `order` | These tools were called in this relative order. |
| `executed` / `executions` | Whether a withdrawal was executed / exactly how many. Read from the transactions table, not the answer. |
| `case_packet_fields` | The created case packet has each field. |
| `forbid_claims` | None of the named claim patterns appears (below). |

Two checks run on **every** case without being listed: no restricted field (date of birth, SSN digits) in
the answer, trace or case packet (GR-09), and exactly one outcome code per turn (GR-20).

### Forbidden claim patterns

Matched programmatically first. Only a match that the patterns cannot settle goes to the judge.

| Name | Fails on phrasing like |
|---|---|
| `waiver_granted` | "we'll waive", "the charge is waived for you", "no surrender charge will apply" (when the quote has one) |
| `advice` | "I recommend", "you should withdraw", "it would be better to" |
| `absence_as_fact` | "SPR doesn't allow", "that isn't possible", "there is no way to" |

## Verdicts

Each case run ends in one of three verdicts:

- **pass**: every expectation holds.
- **fail**: at least one does not. The report names the first failing key.
- **na**: the model call died on a provider error (rate limit, outage, timeout) before the agent could act.
  An `na` measures the endpoint, not the agent: it is excluded from every pass rate and reported separately.
