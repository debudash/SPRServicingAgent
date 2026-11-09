# Cost model

An estimate made before any agent code exists, because its answer changes the architecture. Every figure is
an assumption until B1 measures real token counts. Replace the per-call shapes in §2 with measured values
then (`usage` in `evals/results/<run_id>.json`).

## 1. Prices used

Anthropic first-party API rates, per million tokens, as listed on 2026-11-09.

| Model | Input | Output | Cache read | Cache write (5-minute TTL) | Minimum cacheable prefix |
|---|---|---|---|---|---|
| Claude Sonnet 5.5 (`claude-sonnet-5-5`) | $2.00 | $10.00 | $0.20 (0.1×) | $2.50 (1.25×) | 512 tokens |
| Claude Haiku 5.5 (`claude-haiku-5-5`) | $0.10 | $0.50 | $0.01 (0.1×) | $0.125 (1.25×) | 512 tokens |
| Claude Sonnet 5 (`claude-sonnet-5`, the v1 model) | $2.00 | $10.00 | $0.20 | $2.50 | 1,024 tokens |

Note for M-14: its target ($0.042 per resolved conversation, 2× v1) was set from v1's measured cost, which v1's
config priced at $3 / $15 per million. At today's Sonnet prices v1 would cost about a third less, so the
target is generous by that margin. The target stays as approved; the scorecard reports both.

## 2. Tokens per unit of work (assumed)

One model call per row. "Cacheable" is the stable prefix (tools, system prompt, policy text) plus, within a
case, the conversation history before the newest turn.

| Agent call | Cacheable input | New input written to cache | Never-cached input | Output (incl. thinking) |
|---|---|---|---|---|
| Concierge (per call; ~2 calls per customer turn) | 3,100 | 500 | 0 | 300 |
| Knowledge (retrieved chunks are never cached) | 1,000 | 0 | 1,600 | 250 |
| Transaction (quote or execute) | 1,200 | 0 | 600 | 200 |
| Compliance (system prompt + policy documents cached) | 3,000 | 0 | 900 | 300 |

| Unit of work | Calls | Input | Output | Cacheable share of input |
|---|---|---|---|---|
| B3 routine withdrawal, 4 customer turns | Concierge 8, Transaction 2, Compliance 1 | 36,300 | 3,100 | **83%** |
| B1 product question, 1 customer turn | Concierge 2, Knowledge 1 | 9,800 | 850 | **73%** |

## 3. Cost per conversation and per month

| Design | Routine withdrawal | Product question | 1,000 withdrawals / month | 100,000 withdrawals / month |
|---|---|---|---|---|
| A. Sonnet 5.5 everywhere, no caching | **$0.104** | $0.028 | $104 | $10,360 |
| B. Sonnet 5.5 everywhere, with caching | **$0.051** | $0.016 | $51 | $5,124 |
| C. Haiku 5.5 Concierge, Sonnet 5.5 elsewhere, with caching | **$0.014** | $0.006 | $14 | $1,423 |

## 4. What this decides

1. **Caching is designed in from B1, not retrofitted.** 83% of a withdrawal's input is cacheable, so every
   agent's prompt is built stable-first: tools and system prompt (byte-identical across cases, no
   timestamps or IDs), then the session context, then the conversation. Mid-conversation updates go in as
   new messages, never as edits to the system prompt.
2. **One model everywhere does not meet the target.** Design A breaks the cost target (M-14) and is above
   the $0.10 per-conversation budget (D-10), so an ordinary withdrawal would hit the hard stop and escalate. Design B
   still misses M-14. The model-per-role comparison is therefore required, not optional: the Concierge,
   which makes most of the calls, is the first candidate for a smaller model.
3. **Output is the expensive part.** In design B, output is about 60% of the cost, mostly thinking tokens.
   Effort is set per role: low for the Concierge, higher for Compliance.
4. **What is latency-critical:** Concierge, Knowledge, Transaction and Compliance all run inside a customer
   turn and cannot be batched. Case packets must be ready within a minute (M-12), so they cannot use the
   Batch API either. Eval runs are offline: judge calls go through the Batch API at half price.

## 5. Eval run cost (estimate)

| Run | Case-runs | Estimated cost |
|---|---|---|
| Smoke (about 10 cases, Haiku 5.5, 1 repeat) | ~10 | under $0.25 |
| Full milestone run (active golden + behavioural cases, 3 repeats, one model map) | ~120 | about $5 |
| Model-per-role comparison (two model maps) | ~240 | about $10 |
