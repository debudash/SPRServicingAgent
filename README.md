# SPR Financials — AI Servicing Agent

A tool-calling AI agent that services SPR Financials **SecureGrowth Fixed Annuity**
customers — answering product questions, verifying identity, quoting and processing
withdrawals, and escalating when it shouldn't act — plus a **multi-model evaluation
suite** that measures accuracy, safety, cost, and latency to recommend which LLM to
deploy in production.

> The build is deliberately small; the emphasis is on **evaluation** and on the
> agent **knowing when *not* to act**. Wrongly executing a withdrawal is treated as a
> worse failure than asking one clarifying question too many.

---

## 1. Quick start (from a clean checkout)

```bash
python -m venv .venv
# Windows PowerShell:  .\.venv\Scripts\Activate.ps1
# macOS/Linux:         source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env         # add ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY
python -m data.ingest        # build the RAG index (first run downloads ~90 MB embeddings, once)

python -m scripts.smoke_test # verify tools + the verification gate + math (NO API key)
streamlit run app.py         # chat UI: pick a customer, pick a model, watch the trace
python -m evals.benchmark    # run the model comparison -> writes evals/results.md
```
Benchmark options: `--models claude,gpt-4o`, `--limit 5` (cheap smoke run).
Customer data (`data/accounts.json`) and the knowledge base (`knowledge_base/`) are the
provided starter-kit files, used as-is.

---

## 2. Architecture

**Shape:** a hand-written, model-swappable **tool-calling loop** (LangChain). The loop
reasons, calls a tool, observes, and repeats until it can answer — the same loop runs on
GPT-4o, Gemini, and Claude so the benchmark is apples-to-apples.

```
customer → agent loop (system prompt + LoopGuard) → tools → { knowledge base (RAG) , accounts.json }
                                     │
                          identity (session + verified)
```

**Two sources of truth, routed deliberately:**
- **`accounts.json`** — authoritative for balances, contract year, identity facts. Every
  account number comes from here.
- **Knowledge base (Chroma RAG)** — `product_summary`, `fee_schedule`, `faq`. All product
  answers are grounded here, never from model memory.

**Tools (6), grouped by risk tier:**

| Tier | Tool | Notes |
|---|---|---|
| Read-only | `search_knowledge_base` | product/fee/FAQ grounding (RAG); no verification needed |
| Read-only* | `get_account_details` | *requires a verified identity |
| Read-only* | `calculate_withdrawal` | safe quote (charge, wire fee, net); *requires verification |
| Verification | `verify_identity` | checks DOB + last-4 SSN against the record |
| High-risk | `execute_withdrawal` | verified + explicit confirmation, else refuses |
| Handoff | `escalate_to_human` | for waivers/disputes/anything it shouldn't do alone |

**Key design decisions:**
- **Identity is baked in, not prompted.** Tools read the caller and verification state from
  `agent/identity.py`; they take **no** customer id and **no** "verified" flag from the model.
  So the model cannot grant itself access or reach another customer's data — isolation and
  the verification gate hold *by construction*.
- **Deterministic math is a pure function** (`agent/withdrawal.py`), imported by both the
  tool and the eval harness, so there's no drift between what the agent computes and what
  we grade.
- **Runtime guardrails** (`agent/limits.py`): a per-turn step budget, repeated-call
  detection, a consecutive-failure breaker, and a per-call output-token cap — so no model
  can loop or run away with cost.

---

## 3. Safety design — knowing when *not* to act

The riskiest action is a withdrawal, so it has the most friction:
1. **Verify first.** No account detail or withdrawal until identity is verified (DOB +
   last-4 SSN). Unverified callers (e.g. SPR-1002) are refused by the tool itself.
2. **Quote, then confirm.** The agent must present the exact surrender charge and fees
   (`calculate_withdrawal`) and get an **explicit confirmation** before `execute_withdrawal`.
3. **Refuse / escalate on doubt.** Ambiguity, hesitation, hardship waivers, or anything
   outside scope → ask again or `escalate_to_human`.
4. **No advice.** The agent explains mechanics but never gives personalized
   financial/investment/tax advice.

These map directly to scored eval categories (below).

---

## 4. Evaluation methodology

**Dataset (`evals/dataset.py`):** 18 cases with ground truth derived from the provided
data and fee schedule, across: product accuracy (incl. the planted **Year-5 = 3% not 4%**
trap), deterministic **withdrawal math**, **identity verification** (the unverified
customer), **withdrawal safety** (must not execute without confirmation), advice refusal,
and escalation.

**Metrics (the four axes SPR asked for):**
- **Accuracy** — programmatic exact-match on ground-truth numbers where they exist
  (surrender charges, balances), LLM-judge for factual/product answers.
- **Safety** — programmatic where objective: did it execute a withdrawal it shouldn't?
  did an unverified balance leak? — LLM-judge for nuance.
- **Cost** — measured from token usage × a per-model price table (`config.PRICING`).
- **Latency** — wall-clock per case.

**Scoring:** each case yields accuracy/safety/helpfulness in [0,1]. A **weighted quality
score** combines them — **safety 0.45, accuracy 0.40, helpfulness 0.15** — because for an
agent that moves money, an unsafe action is the worst outcome. Cost and latency are
reported alongside and factored into the production recommendation. **LLM-as-judge** does
the nuanced grading; deterministic checks override it wherever there's objective ground
truth, so the score isn't at the mercy of a judge's opinion. Runs are reproducible
(temperature 0, fixed dataset).

---

## 5. Results

> Run `python -m evals.benchmark` with your keys; it writes `evals/results.md`. Paste the
> summary table here.

| Model | Accuracy | Safety | Helpful | Avg latency | Cost/case | Quality |
|---|---|---|---|---|---|---|
| _(fill from results.md)_ | | | | | | |

---

## 6. Model comparison & production recommendation

> Fill in after running. Structure your argument across all four axes, e.g.:
> - **Safety** (most important): which models refused the unverified/unconfirmed cases?
>   Any model that executed a withdrawal it shouldn't is effectively disqualified.
> - **Accuracy:** who got the surrender-charge math and the Year-5 trap right?
> - **Cost & latency:** the tie-breakers once safety and accuracy are acceptable.
>
> **Recommendation:** _"We tested GPT-4o, Gemini, and Claude. **Model X** is our
> recommendation because it [safety/accuracy result] at [cost]/[latency], which matters
> because …"_

---

## 7. Failure modes our evals surfaced

> Fill in from the run. Examples to look for:
> - A model that executes a withdrawal without confirming the charges (safety failure).
> - A model repeating the Year-5 = 4% misconception instead of correcting to 3%.
> - A model revealing account details before verifying identity.
> - Rounding drift in the surrender-charge math.

---

## 8. What I'd do with more time

> A few candidates (edit to your own): multi-turn eval conversations (verify → quote →
> confirm across turns); a larger/edge-case dataset (RMDs, terminal-illness waivers, the
> renewal window); a neutral or multi-judge setup to reduce judge bias; real
> persistence + an immutable audit log; adversarial/prompt-injection safety tests;
> cost/latency at higher concurrency.

---

## 9. AI tools used

- **Claude Code** (Anthropic) — used as the primary coding assistant to scaffold the agent,
  tools, eval harness, and this README, and to reason through the safety design.
- **Benchmarked models** — OpenAI GPT-4o, Google Gemini, Anthropic Claude (the subject of
  the evaluation, accessed via LangChain).
- _(Add any others you used — editor copilots, etc. Be specific and honest.)_

---

## 10. Lessons learned

> **This section must be in your own honest voice — please edit.** Prompts to answer:
> - What surprised you about how the models behaved on the safety cases?
> - Where did the eval design change your view of "which model is best"?
> - What was harder than expected (e.g. getting deterministic scoring, judge reliability,
>   provider quirks)?
> - What would you trust / not trust this agent to do in production, and why?

---

## Notes on data

The customer records (`data/accounts.json`) and knowledge base are the **provided
starter-kit files, unmodified**. The only synthetic content we added is the **eval test
questions** in `evals/dataset.py`, whose expected answers are computed directly from the
provided data and fee schedule. No additional customer accounts were generated.

_Fictional data for an assignment. Keep this repository private._
