# Design decisions

Why the agent and its evals are built the way they are. Each entry records the decision,
the reasoning, and what was rejected — the code shows *what*, this shows *why*.

---

## Agent

### 1. Identity is two gates in series, not one flag

`accounts.json`'s `identity_verified` means **SPR verified this customer out of band**
(KYC/servicing records) — the record can be trusted for financial transactions. It is
static, and nothing said in a chat can earn it.

- **Gate A — account trust.** Read live from the record. False ⇒ full stop: the customer
  is told to verify with SPR directly. `verify_identity` refuses *before* checking any
  credentials, so correct credentials on an untrusted account grant nothing.
- **Gate B — session challenge.** Date of birth + last 4 of SSN, via `verify_identity`.
  Starts unpassed every session for *everyone*, and only counts on an account that
  passed Gate A.

Account-specific tools require **both** (`identity.is_verified()`).

**Rejected:** treating `identity_verified` as the *starting value* of a single mutable
session flag. That let an unverified customer self-promote to verified by answering two
knowledge questions in chat, and then withdraw money. It also meant a trusted customer
was never challenged at all, so `verify_identity` was dead code for them.

### 2. Confirm-before-execute is enforced in code, not just prompted

`execute_withdrawal` refuses any amount that hasn't been quoted via
`calculate_withdrawal` this session (`identity.is_quoted`).

The rule "show the charges and get an explicit yes" existed only in the system prompt,
and `guardrails.needs_human_approval()` was defined but never called. A model could — and
did — go straight from `verify_identity` to moving money without ever showing the numbers.

**Deliberately not enforced in code:** whether the customer's "yes" is genuine. Reading
intent from free text is a judgment call; the code guarantees the *numbers were shown*,
the prompt and evals cover the intent.

### 3. The agent is told Gate A up front, not left to discover it

`react_agent.new_messages()` injects a session-context message stating whether the
account is trusted. Gate A is known the moment the session starts.

**Why:** without it, an unverified customer was asked for their date of birth and SSN and
only learned the account was ineligible *after* handing them over. Asking for credentials
that cannot possibly help is a bad experience and poor practice with sensitive data.

Consequence: `identity.login()` must be called *before* `new_messages()`.

### 4. Verification persists across turns

`identity.login()` is called once per session (on customer change), not per message.
Calling it every turn reset Gate B to the record's static value, so a customer had to
re-verify on every single message.

### 5. The loop guard compares against the previous call only

`LoopGuard` flags a repeat only when it matches the *immediately preceding* call, not any
call seen this turn.

**Why:** `calculate_withdrawal` → `verify_identity` → `calculate_withdrawal` is a
legitimate retry after a precondition was fixed, not a loop. The old "seen anywhere this
turn" rule aborted it as "no progress". Genuine oscillation is still bounded by
`MAX_AGENT_STEPS`.

### 6. Step budget raised 6 → 8

Multi-step cases need ~5 tool calls. At 6, one exploratory detour tripped the guardrail
and the case failed for reasons unrelated to model capability — measuring the guardrail
instead of the model.

---

## Evals

### 7. Programmatic wherever there is ground truth; the judge only for nuance

Every axis the LLM judge scores carries run-to-run variance, and safety is the axis that
blocks deployment (decision 15) — so it must not rest on a grader that wobbles.
Deterministic checks: `expected_numbers`, `must_call`,
`must_mention`, `must_execute` / `must_not_execute`, `must_not_reveal`.

All are **symmetric** — a case that demonstrably passes scores 1.0 rather than silently
falling through to the judge. (`must_not_reveal` originally only scored the *failure*
case, so every correct refusal was judged instead of measured.)

Expectation strings are **grounded empirically** — probed against all three models
before being encoded — so they capture real content gaps rather than phrasing
differences. `'not personalized'` and `'confirm'` were dropped for exactly this reason.

### 8. `must_call` is a grounding check: the right answer for the right reason

A model can state "hardship waivers require documentation" from memory without ever
opening the knowledge base. Identical words, zero evidence. In a regulated domain that is
a failure, and outcome-only scoring cannot see it.

This is the sharpest discriminator in the suite: gpt-4o produced correct figures on
`step-premise` while never checking the premise against the KB.

### 9. A judge failure is not a zero

An unparseable judge reply yields `None`, is retried once, and is excluded from averages
— never scored 0.0. Scoring it as zero made a *harness* failure indistinguishable from a
model doing something unsafe — on what was then the most heavily weighted axis, and is
now the gate. A rate-limited judge once cost a model 12 points this way.

A model with judge failures is marked **NOT COMPARABLE** and the winner line is
suppressed: it was scored on fewer axes than the others, so it isn't a ranking.

### 10. The judge is not a contestant

`JUDGE_MODEL=openrouter` (NVIDIA Nemotron via OpenRouter) is deliberately excluded from
`model_names()`. Claude previously judged a lineup containing Claude, and finished first
at exactly 100.0 — self-preference bias in a benchmark meant to justify a deployment
choice.

The judge also needs `temperature=0` for reproducibility, which `claude-sonnet-5` does
not accept. Candidates were tested for JSON compliance, stability across repeats, and
whether they actually discriminate good answers from bad — a judge that always returns
1.0 is useless.

### 11. Discrete 0 / 0.5 / 1.0 rubric

Models reproduce a 3-point classification far more reliably than "is this 0.85 or 0.6?".
`parse_judge` snaps stray values to the scale, otherwise a judge ignoring the instruction
reintroduces the drift the scale exists to remove.

### 12. Steps and guardrail trips are reported, never scored

Rewarding fewer steps would push the agent to skip the very evidence-gathering that
decision 8 requires. Efficiency informs the deployment call; it must not trade off
against grounding or safety. Reported alongside cost and latency.

### 13. `challenge_passed` keeps identity from confounding every case

Models a caller who cleared Gate B earlier in the call. Set on every case *except* the
`id-*` ones, where the gates are the subject under test. It grants Gate B only — it
**cannot** bypass Gate A, so a case cannot accidentally rescue an untrusted account.

### 14. Cases were relaxed rather than the prompt rewritten

`step-hardship` originally required `calculate_withdrawal`, but the system prompt tells
the agent to escalate hardship waivers — so the case was penalising instruction-following.

Fixing the prompt after seeing scores is teaching to the test. The case was narrowed to
what it should measure (was the waiver rule grounded in the KB) instead.

*Left open:* whether the agent should hand off a hardship request *with* the concrete
facts attached rather than escalating cold. That is a genuine agent-design question and
deserves deciding on its merits, not because a case failed.

### 15. Safety is a gate, not a weighted axis — and it gates on *measured* safety only

Safety was 45% of a weighted quality score. Two things were wrong with that:

- It implies a model can **offset a safety deficit with speed or accuracy** — which
  nobody would defend once said out loud. A model that leaked an unverified balance
  lost ~2 points and could still rank first.
- When every candidate passes, 45% of the score is a *constant*, damping the real
  differences. Re-scoring the same run widened the spread from 4.4 to 7.9 points
  (1.8×) without changing a single measurement.

Now: safety is pass/fail (`SAFETY_GATE`), failures are printed as `FAILED SAFETY GATE
— not ranked`, and quality ranks only gate-passers on accuracy and helpfulness with
the original weights renormalised (0.727 / 0.273).

The gate uses **deterministic safety only** (16 of 22 cases — executed / leaked /
refused). Judge-scored safety is reported but advisory: a blocking criterion must not
depend on a grader that can wobble, or judge noise disqualifies a model that did
nothing wrong. Verified: a 0.5 judge score on a non-safety case no longer fails the
gate, while a genuine measured failure still does.

### 16. Model selection is not a safety decision here

Safety came out 100% with zero variance across all three models and 66 runs, because
it is enforced in code rather than left to model judgment. That makes model choice a
**cost / latency / quality** decision, not a safety one.

The only axis that discriminates is grounding, where no candidate is close to a
defensible bar: best observed rate 0.50 (95% CI [0.19, 0.81]), `pass^3` ≈ 0.12, against
harm-tolerance arithmetic implying ~99%+ for regulated servicing. So grounding is being
made **structural** (retrieval-always / forced tool use / citation enforcement) rather
than solved by picking a model — the same move that made safety stable.

Recommendation therefore falls to cost and latency, which point to **GPT-4o** — cheapest
per case and ~3× faster than Gemini. Gemini ranks first on quality, but that lead is
almost entirely the grounding cases, where its own rate (0.50) is nowhere near a
deployable bar; selecting for it means picking the least-bad model at something being
fixed in code anyway. The two models' weaknesses also differ in kind: Gemini's is
run-to-run *inconsistency*, which no prompt fixes, while GPT-4o's is a reproducible gap
in escalation helpfulness (`escalate`, `step-hardship`), which is promptable. Selection
is a two-way door — swapping models is one word.

Conditions: force retrieval in code first, re-run the suite after (the one change that
could reopen the choice), and shadow-evaluate before live traffic. Offline evals narrow
candidates; they do not make the call.

### 17. `--repeat N` for agentic variance

Agentic behaviour is not deterministic: Gemini grounded `step-hardship` fully on one run
and skipped the lookup on the next. A single run of a multi-step case is a coin flip
reported as a measurement. `--repeat` averages N runs and flags cases where runs
disagreed (`VARIED across runs`) rather than hiding it in the mean.

### 18. Three test levels, cheapest first — and a known gap is not a failure

`scripts/smoke_test.py` (no API key) proves the *code*: both gates, the quote-before-execute
rule, the math. `scripts/demo.py` (~25s, one model) proves the *behaviour*: six scenarios
checked programmatically, no judge. `evals/benchmark.py` (minutes, three models) picks a
model. Each level is a different question, so each is worth running separately.

The demo's scenarios and checks live in one place and are imported by both the CLI and the
Streamlit page, the same way `withdrawal.py` is shared by the tool and the eval harness —
two surfaces, one definition, no drift.

The escalation scenario **fails** on gpt-4o: it answers the hardship-waiver rule from memory
without opening the knowledge base. It is marked `known_gap`, printed as `GAP` rather than
`FAIL`, and excluded from the exit code.

**Rejected:** relaxing the check so the demo runs clean. The scenario is the most interesting
thing the evals found, and weakening the assertion to get a green run is teaching to the test
(decision 14). Marking it keeps the demo honest *and* keeps the exit code meaningful — a real
regression still turns the run red.

---

## Provider constraints worth knowing

- **`claude-sonnet-5` rejects any `temperature` override** (400). It is omitted for that
  provider; GPT-4o and Gemini still get `temperature=0`.
- **`claude-sonnet-5` always emits a `thinking` content block** that cannot be disabled.
  Anything extracting text must select `text`-typed blocks only — a naive
  `b.get("text", b)` dumps the raw base64 signature payload into the answer.
- **Gemini** ignores `temperature` on some models (warns rather than failing).
- **OpenRouter free tier** is 50 model requests/day; a full 3-model run needs 66. Adding
  credits raises it to 1000/day.
