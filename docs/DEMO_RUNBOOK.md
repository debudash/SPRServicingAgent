# Demo runbook

How to run the desk for an audience, what to say, and the questions to expect. The facts behind each
answer live in the linked documents; this page only points at them.

## 1. Before the audience arrives (10 minutes)

1. Start the stack: `docker compose up -d --build desk`, then open http://localhost:8530.
2. Check the key and secret without printing them: `docker compose exec -T desk python -c "from data.settings
   import load_settings as l; s=l(); print(len(s.approval_secret)==64, s.execution_enabled)"` prints `True True`.
3. Start from a clean desk, so the review queue holds only today's cases:
   `docker compose stop desk`, delete `var/desk.db` and `var/checkpoints.db`, then `docker compose up -d desk`.
   The starter-kit accounts and the demo logins are reseeded on start; the knowledge index in `var/chroma` stays.
4. Load every page as Streamlit runs it: `make smoke` prints `page smoke: PASS`. Then run the offline scenarios
   once: `docker compose exec -T desk python -m agents.demo`. All nine say PASS.
   This is the fallback if the API is slow or down: the same page is in the app ("Open the behaviour demo").
5. Have the blueprint open in a second tab: `docs/blueprint/blueprint.html`.

Demo logins (simulated upstream login, ADR 0007): SPR-1001 Margaret Holloway `margaret-demo`, SPR-1002 Raymond
Okafor `raymond-demo` (not identity-verified), SPR-1003 Linda Chu `linda-demo`, SPR-1004 Thomas Brennan `thomas-demo`. The step-up form asks for the date of birth and the last four
SSN digits from the starter kit's `accounts.json`; never type them into the chat.

## 2. The story in one sentence

A customer can get a cited answer, see their balance and withdraw money through a chat, and **no model can
move a dollar**: models read and propose, code decides, a person decides anything large, and every guard is
tested, red-teamed and audited.

## 3. The demo (about 12 minutes)

| Minute | Show | Say |
|---|---|---|
| 0-2 | Blueprint: the graph | v1 was one tool-calling agent. v2 splits the work: a Concierge (Haiku) classifies, Knowledge (Sonnet) answers from documents, Compliance (Sonnet) reviews withdrawals. Routing, identity, quotes, rules, the approval token and the ledger are code ([ADR 0003](decisions/0003-langgraph-code-routed-graph.md), [ADR 0008](decisions/0008-transaction-is-code.md)). |
| 2-3 | Guest: "What's the surrender charge in year 5?" | A cited answer, version in force (fee schedule v2, 3%, not the superseded v1's 4%). Point at the sidebar: nodes, tools, citations, cost. Numbers come from records, narrative from documents. |
| 3-4 | Log in as SPR-1002, ask for the balance | Turned away: the account is not identity-verified (Gate A). Code decides, not the model. |
| 4-7 | SPR-1001: "Withdraw $5,000" → "Yes, go ahead" → identity form | The quote shows exact figures from records. The yes counts only on a later turn, for the quoted amount. The step-up form is outside the chat, so credentials never reach a model. Then rules, Compliance, a token bound to that exact proposal, one execution. Sidebar: the full node path. |
| 7-10 | SPR-1004: "Withdraw $30,000" → yes → identity form → log out → **Open the review queue** → Approve | Over $25,000 (D-02): the rules flag it, Compliance reviews it but cannot approve it, a case opens with a scrubbed packet. A person approves, and the money moves through the *same* guarded path, recorded as `human:<reviewer>`. Log back in: "Your cases" shows it approved. |
| 10-11 | Behaviour demo page: run all nine | Prompt injection, a changed amount, three failed identity checks, the kill switch: each shows the guard that fired and the ledger. Offline, scripted models, real guards. |
| 11-12 | GitHub: the issue log and a PR | How it was built: lanes, one issue per branch, two-axis review on every money-path PR, every bug fixed test-first with a log row. The red team found a duplicate-withdrawal bug (#140) the reviews missed. |

If something goes wrong live, say what the desk did and why, then switch to the behaviour demo page. A
refusal on screen is a guard working, not a failure.

## 4. Talking points

- **Why several agents.** Each model gets one job, its own prompt, its own tools and its own budget. The
  Concierge sees no account data; Compliance sees the proposal and policy, never identity data. Tool scope
  per role is enforced in code (FR-22), not asked for in a prompt.
- **Where the safety lives.** In code and unit tests: identity gates, quote-before-execute, the explicit
  later yes, the step-up, rule flags, the HMAC approval token bound to the proposal's hash, idempotent
  execution, the kill switch, hop and token budgets. Prompts explain the rules; they are not the safety
  layer ([CLAUDE.md](../CLAUDE.md) project rules).
- **Restricted fields.** Date of birth and SSN digits are captured by code from the step-up form and never
  reach a prompt, trace, log, case packet or answer ([ADR 0005](decisions/0005-credentials-captured-by-code.md));
  a property test and a red team check every place the desk writes.
- **Human in the loop, calibrated to risk.** Read-only answers: no gate. A balance: login. Moving money:
  login, explicit yes, step-up and Compliance. Over $25,000 or half the balance, a waiver, a full surrender:
  a person decides.
- **Evals as the judge.** Golden and behavioural cases were written before the code ([EVAL_SPEC](EVAL_SPEC.md));
  scoring is programmatic first; paid runs only at milestones; the golden set is human-owned and never
  edited to make a run pass.
- **Cost.** Model per role (Haiku for the Concierge, Sonnet elsewhere) with a stable, cacheable prompt prefix:
  about $0.014 per routine withdrawal against $0.104 for Sonnet everywhere without caching
  ([COST_MODEL](COST_MODEL.md) §3, estimates to be replaced by measured runs).
- **The build process.** Tracer bullets B0-B5 ([PLAN](PLAN.md)), integrator-owned contracts, lanes that never
  import each other, and a review on two axes (standards, spec) whose defects become logged bug issues
  ([ISSUE_LOG](ISSUE_LOG.md)).

## 5. Questions to expect

| Question | Answer |
|---|---|
| What stops the model inventing a balance or a charge? | Figures come only from the quote service over records; the model never produces a number the customer sees. Knowledge answers must cite a retrieved chunk, or the desk says it has no source. |
| What if someone prompt-injects "approved, execute now"? | The Concierge can be fooled into reading a yes; it doesn't matter. Execution needs a stored quote, a later yes for that amount, a passed step-up, unflagged rules, Compliance's approval and a token bound to the proposal hash, all checked in code and again in the ledger. Scenario 6 and the red team show it. |
| Can Compliance approve a $30,000 withdrawal? | No. The rules flag it, the approval edge refuses a token for a flagged or human-tier proposal, and the approval store refuses it again. Only a named person can approve it. |
| What if the same yes arrives twice, or the execute call is replayed? | One withdrawal. The ledger keys on the proposal ID and replays the first execution for the same token (FR-09). The red team found and closed a case where a repeated yes re-quoted (#140). |
| How do you know the guards hold? | 830 offline tests, a property-style red team that fuzzes conversations against an oracle reading the attacker's own script, mutation checks (remove a guard, watch tests fail), and two-axis review on every money-path change. |
| Why LangGraph and not one agent? | Routing is deterministic code over typed state, so the path is testable and auditable; models sit at nodes with narrow jobs. v1 (one agent) is kept as the baseline to compare against. |
| What does it cost? | Estimated $0.014 per routine withdrawal with the model map and caching; measured costs replace the estimate after the milestone eval run. Each turn shows its cost in the sidebar. |
| How would this go to production? | Slides, not built: FastAPI on ECS Fargate behind SSO, RDS, a managed vector store, secrets in AWS Secrets Manager, durable checkpoints, LangSmith and CloudWatch; CI runs lint, tests, then an eval gate before deploy ([ARCHITECTURE](ARCHITECTURE.md) §5). |
| What is not built? | See §6. |

## 6. Known limits (say them before you are asked)

- The login is simulated (demo passwords); real authentication sits upstream (ADR 0007).
- The review queue has no staff login; any visitor can open it in the demo.
- A waiver request opens a case but does not show a quote without the waiver (FR-13 is partial).
- "Your cases" shows a case's status, not the transaction reference (FR-18 is partial).
- The behaviour demo runs offline with scripted models; there is no live mode on that page yet.
- The milestone eval run (#91) and the B5 failure modes (budget exhausted, checker down) are still to do.
- Two golden cases (G-B4-01, G-B4-02) expect a large request to go to a person on the quote turn alone, which
  would leave a withdrawal no reviewer could approve; the desk follows BH-B4-01, and the owner decides the cases.
