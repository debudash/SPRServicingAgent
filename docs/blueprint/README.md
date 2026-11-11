# Blueprint: SPR Servicing Desk (v2)

The design every lane builds against, **updated 2026-11-11 to match the code on `main`** (contracts 0.6.2,
B1 to B4 built). Requirement IDs refer to [PRD.md](../PRD.md), rules to [GROUNDING_RULES.md](../GROUNDING_RULES.md),
bullets to [PLAN.md](../PLAN.md). Decisions: [ADR 0003](../decisions/0003-langgraph-code-routed-graph.md)
(framework and topology), [ADR 0004](../decisions/0004-model-per-role.md) (models),
[ADR 0005](../decisions/0005-credentials-captured-by-code.md) (credentials),
[ADR 0006](../decisions/0006-onnx-embeddings.md) (embeddings), [ADR 0007](../decisions/0007-login-and-step-up.md)
(login and step-up), [ADR 0008](../decisions/0008-transaction-is-code.md) (Transaction is code).
Data model, flows, trust boundaries and deployment: [ARCHITECTURE.md](../ARCHITECTURE.md). A slide version is in
`blueprint.html`, published at https://claude.ai/artifact/JqUdFUhq3BoiMUt2Mh7kWd (private to the owner until shared).
Where the code does not yet do what the design says, §12 lists the gap.

## 1. The shape in one paragraph

A **LangGraph** graph runs one customer turn. Three agents call a model: the **Concierge** reads what the
customer wants, **Knowledge** answers product questions from cited documents, and **Compliance** checks a
withdrawal for coercion, third parties and confusion. Everything else is code: the identity gate, the quote,
the rules, the approval token, execution, the case packet and the reply. **Code** decides which node runs
next. Every money movement follows the same fixed path: **quote → explicit yes → step-up → rules →
Compliance → approval → execute**, or a case for a person, who approves through the same token and ledger.
Models judge inside a node. They never choose the next node, never write a figure, and never hold the
authority to move money.

## 2. The graph

```mermaid
flowchart LR
    IN[intake<br/><i>code</i>] --> CON[concierge<br/><i>Haiku</i>]
    IN -->|step-up form| ID
    CON -->|product question, waiver, RMD| KN[knowledge<br/><i>Sonnet</i>]
    CON -->|account or withdrawal| ID[identity_gate<br/><i>code</i>]
    CON -->|third party, full surrender| CASE[case<br/><i>code</i>]
    ID -->|logged in, account question| ACC[account<br/><i>code</i>]
    ID -->|withdrawal amount| TX[transaction<br/><i>code</i>]
    ID -->|yes to the shown quote| CF[confirm<br/><i>code</i>]
    TX --> CF
    ID -->|step-up passed| RU[rules<br/><i>code</i>]
    ID -->|third failure| CASE
    CF -->|human-tier review| CASE
    RU --> CO[compliance<br/><i>Sonnet</i>]
    CO --> AP[approval<br/><i>code</i>]
    AP -->|approve and no flags| EX[execute<br/><i>code</i>]
    AP -->|hold, escalate or any flag| CASE
    KN --> RESP[respond<br/><i>code</i>]
    ACC --> RESP
    CF --> RESP
    EX --> RESP
    CASE --> RESP
    CASE -. packet in desk.db .-> RQ{{review queue<br/><i>a person</i>}}
    RQ -. approve: same token + ledger .-> DB[(desk.db)]
```

A quote turn ends at `respond` with the figures shown. The customer's yes on a later turn passes `confirm`,
then the step-up form (Gate B) on the turn after that, then `rules` onward. Any node that sets a turn failure
(budget, contract violation, fail-closed) routes straight to `respond`.

| Node | Kind | What it does | Writes to state |
|---|---|---|---|
| `intake` | code | Binds the customer and Gate A, loads switches and versions, captures credential-shaped text and masks it before any model sees the turn (ADR 0005) | `conversation_id`, `as_of`, `session`, `switches`, `versions` |
| `concierge` | LLM, Haiku 5.5 | Classifies intent and extracts the amount and an explicit yes; never answers product or account questions itself | `intent` |
| `identity_gate` | code | Gate A (`identity_verified` on the record), the login (ADR 0007), and Gate B: the step-up form checked against the `identity` table; the third failure locks and voids a confirmed proposal (D-08) | `gate`, `session.gate_b_passed`, `failed_attempts`, `locked` |
| `knowledge` | LLM, Sonnet 5.5 | Retrieves from the knowledge base and answers with citations | `knowledge_answer` |
| `account` | code | Reads the account view without restricted fields | `account_view` |
| `transaction` | code (ADR 0008) | Calls the quote calculator (code computes every figure) and stores the proposal with its hash | `proposal` |
| `confirm` | code | Accepts only an explicit yes, given after the quote, for the proposal's exact amount (GR-17) | `confirmation` |
| `rules` | code | Flags: over $25,000 or 50% (D-02), not active, waiver request, full surrender, age 80+ over the allowance (D-07), execution switched off (FR-26), an open review in this conversation (FR-12) | `rule_flags` |
| `compliance` | LLM, Sonnet 5.5 | Reviews the proposal, flags and policy sections for coercion, third parties and confusion; returns approve, hold or escalate with reasons | `compliance` |
| `approval` | code | Issues the token (HMAC over the proposal hash) only if the decision is approve **and** there are no rule flags (FR-11) | `approval` |
| `execute` | code | Checks the token against the proposal hash and executes once in one DB transaction with its audit row | `execution` |
| `case` | code | Opens a case with a scrubbed packet: masked customer turns, scrubbed again, plus fixed wording (FR-16) | `case_packet` |
| `respond` | code | Builds the reply from the structured result, with one outcome code per turn (GR-20). No model writes it | `reply` |

**Routing is code.** Edges are functions of state (`intent`, `gate`, `confirmation`, `rule_flags`,
`compliance`, `approval`, `switches`) in `agents/graph.py`, not model choices. The only model output that
steers routing is the Concierge's `intent`, and every intent still passes the same gates.

## 3. Agents, models and tool scope

Each role's tools are registered for that role only (`contracts/tools.py` `TOOL_SCOPE`). Calling another
role's tool is refused in code and logged (FR-22).

| Agent | Model | Effort | Tools it may call | It never |
|---|---|---|---|---|
| Concierge | Haiku 5.5 | low | none: credentials never reach it | quotes, answers product facts, approves, sees DOB or SSN digits |
| Knowledge | Sonnet 5.5 | medium | `search_kb` | reads account data |
| Compliance | Sonnet 5.5 | high | `get_policy` (policy documents only) | executes, edits a proposal |
| Transaction | code (ADR 0008) | n/a | `get_account`, `quote`, `propose` | approves its own proposal, executes |
| Case | code | n/a | writes the case store directly | decides the case |

Only the three model roles get a model (`agents/runner.py` `_MODEL_ROLES`). `execute` is not a tool any role
can call; only the `execute` node and the reviewer's approve run the ledger, and both need a valid token.

## 4. Conversation state (one writer per field)

Typed in `contracts/state.py` (`FIELD_WRITERS`, `SESSION_FIELD_WRITERS`, `check_write`). A write from any other
node is a contract violation and fails the turn closed (FR-19).

| Field | Writer | Notes |
|---|---|---|
| `conversation_id`, `as_of`, `switches`, `versions` | `intake` | `versions`: model, prompt and policy-document versions, copied into audit rows |
| `session` | `intake` creates it; then field by field | Never replaced whole after creation (#23). Never holds DOB or SSN |
| `session.customer_id`, `gate_a_trusted`, `authenticated` | `intake` | `authenticated` comes from the login (ADR 0007) |
| `session.gate_b_passed`, `failed_attempts`, `locked` | `identity_gate` | The third failure locks (D-08) |
| `turn`, `budgets`, `transcript`, `trace` | runner | The transcript holds masked text only; a step-up is kept as `[identity check submitted]` |
| `intent` | `concierge` | Kind, amount, explicit-yes flag |
| `gate` | `identity_gate` | This turn's decision; cleared at the start of every turn |
| `account_view` | `account` | Balance, contract year, age band, allowance remaining |
| `knowledge_answer` | `knowledge` | Answer text plus citations (`doc_id`, `version`, `section`) |
| `proposal` | `transaction` | Holds the quote; the hash covers customer, amount, every figure, as-of date and contracts version |
| `confirmation` | `confirm` | Proposal ID and turn number of the explicit yes |
| `rule_flags` | `rules` | |
| `compliance` | `compliance` | Decision, reasons, vulnerable-customer signals |
| `approval` | `approval` | Holds `token_hmac` exactly when the decision is approve and no flag is raised; single use |
| `execution` | `execute` | Transaction ID; the proposal ID is the idempotency key |
| `case_packet` | `case` | Its `case_id` is the reference shown to the customer |
| `reply` | `respond` | Text, citations and the turn's one outcome |
| `human_decision` | reserved for `human_review` | Not written: the reviewer decides outside the graph (§7) |

Outcomes (`contracts/outcomes.py`): `ANSWERED`, `EXECUTED`, `NO_SOURCE`, `NOT_PERMITTED`, `NEEDS_HUMAN`,
`UNAVAILABLE`, `OUT_OF_SCOPE`.

## 5. Identity: login, then step-up (ADR 0007)

- **Login** (simulated upstream SSO): the customer picks their ID and enters a password on the login page.
  `runner.login` checks it against the `logins` table and opens a session with `authenticated=True`. Demo
  passwords are seeded when `DESK_DEMO_LOGINS=true`.
- **Gate A** is static account trust: `identity_verified` on the record, re-read every turn. An untrusted
  account is refused with the contact number and never asked for credentials (FR-03, GR-14).
- **Logged in + Gate A** is enough to read the account (`LOGGED_IN`).
- **Gate B** is the step-up before money moves: a masked form asks for the date of birth and the last four SSN
  digits after the customer says yes to a quote. Only `identity_gate` checks them, through `data/identity.py`.
  Credentials typed into the chat are masked and never checked.
- **Three failures** lock the session, void the confirmed proposal and open a case (D-08).

## 6. Data

| Store | What | Who can read it |
|---|---|---|
| `desk.db` (SQLite) · `accounts`, `beneficiaries` | Account record without restricted fields | `account`, `transaction`, `rules` |
| `desk.db` · `identity`, `logins` | DOB and SSN last 4 (PG-04); login passwords | `data/identity.py` only, by function call; never returned |
| `desk.db` · `proposals`, `approvals`, `transactions` | Quotes and hashes; approval tokens; withdrawals (seeded history for D-05) | the money path and the review desk |
| `desk.db` · `cases` | Case packets: the review queue | `case`, the reviewer UI |
| `desk.db` · `audit`, `conversations` | Append-only, hash-chained audit (triggers block UPDATE and DELETE) | written by every deciding node; read with `verify_chain` |
| `knowledge/` → Chroma | Versioned markdown documents (`doc_id`, `version`, `effective_date`) chunked by section | `knowledge`; `compliance` sees policy documents only |

- **Clock:** one configured as-of date, 2024-12-01 (D-04). Contract year and age derive from it.
- **Scrubber:** `agents/guards/credentials.py` captures credential-shaped text for the gate and masks it before
  any prompt, trace, log or case packet. Unit-tested and fuzzed by the red team.
- **Knowledge documents** live in `knowledge/` (integrator-owned): the three starter documents, three synthetic
  SPR operations documents (large withdrawals, vulnerable customers and third parties, the waiver review
  procedure; PRD O-02) and a superseded fee-schedule version.
- **Embeddings:** Chroma's built-in ONNX all-MiniLM-L6-v2 (ADR 0006). No network at test time.

## 7. The human review path (B4)

The `case` node writes the packet to `desk.db` and the turn ends with `NEEDS_HUMAN` and the case reference.
The graph does not pause. A reviewer opens the review queue in the same app (`agents/review.py`,
`AgentReviewDesk`) and approves, rejects or asks for information:

- **Approve** a withdrawal case: the desk re-checks that the proposal was confirmed and escalated, issues a
  token bound to its hash, records the approval as `human:<reviewer>`, and executes once through the same
  ledger. The ledger still honours the kill switch.
- **Reject** voids the proposal. **Ask for information** records the request.
- Cases with no proposal (lock, third party, waiver, hardship, RMD, full surrender) record the decision only;
  no money moves through the desk for them (NG-01, NG-07).
- The customer sees the result under "Your cases" when they log in again.

## 8. Prompt layout for caching

Every model request is built stable-first: the system prompt (a versioned file in `agents/prompts/`, no
dates, IDs or customer data) with an ephemeral `cache_control` breakpoint, then the session context, then the
conversation (`agents/llm.py`).

## 9. Guards, budgets and switches

| Guard | Where | Requirement |
|---|---|---|
| Login and Gate A before any account read; step-up before money moves | `identity_gate` + edges | FR-02, GR-12 |
| No credentials asked on an untrusted account | `identity_gate` | FR-03, GR-14 |
| Quote, explicit yes, step-up and token before execute | `confirm`, `identity_gate`, `approval`, `execute` | FR-08, GR-16 to GR-18 |
| Compliance cannot approve a flagged proposal | `approval` | FR-11 |
| One withdrawal per proposal | ledger (proposal ID unique) | FR-09 |
| Tool scope per role | `agents/tools/registry.py` | FR-22 |
| Contract validation on every state write | runner (`check_write`) | FR-19 |
| Budgets: 8 hops, 12 tool calls, 30 s per turn; running out ends the turn `UNAVAILABLE` | runner (`_guarded`, `spend_tool_call`) | FR-20, D-10 |
| Fail closed when Compliance or the queue is down | edges | FR-21, GR-21 |
| Kill switch on execution: `EXECUTION_ENABLED=false` raises a rule flag, so the withdrawal goes to a case; the ledger refuses too | `rules`, ledger | FR-26 |

## 10. Observability, audit and proof

- **Tracing:** model calls go through `ChatAnthropic` (langchain-anthropic), so LangSmith traces them when its
  environment switch and key are set. Text is masked before any model sees it.
- **Audit:** separate from traces, in `desk.db`, hash-chained. Every deciding node writes a row with the versions
  in force (FR-25).
- **Offline proof:** `python -m agents.demo` plays nine scripted conversations through the real desk (also a
  page in the app); `make smoke` loads every page as Streamlit runs it; the red team (`redteam/`) fuzzes the money
  path and restricted fields; `make check` runs 830+ offline tests.

## 11. Runtime and layout

| Service | In `compose.yaml` | Port (host) |
|---|---|---|
| `desk`: Streamlit login, chat, step-up form, review queue and behaviour demo | yes | 8530 |
| `checks`: the CI check suite in the same image | yes | none |

```
contracts/             integrator   state.py, messages.py, tools.py, outcomes.py, ports.py, money.py
knowledge/             integrator   versioned knowledge documents
data/                  data lane
  identity.py          money path   the only door to the identity and logins tables
  store/                            schema, migrations, seed, accounts, proposals, quotes, cases,
                                    ledger (money path), audit (append-only, records, never decides)
  knowledge_index/                  ingestion, retrieval, policy source for Compliance
  clock.py, settings.py
agents/                agents lane
  graph.py                          the LangGraph graph and routing functions
  runner.py                         turns, login, step-up, budgets, transcript
  nodes/                            one module per node; transaction, confirm, rules, compliance,
                                    approval, execute and identity_gate are the money path
  guards/credentials.py             capture and mask credentials (ADR 0005)
  review.py            money path   the reviewer's side (approve, reject, ask)
  tools/registry.py                 tool scope per role
  llm.py, prompts/, config/         models per role, versioned prompts
  wiring.py                         builds the desk from settings; the demo's scratch desk
  ui/                               Streamlit app and the page smoke
  demo/                             nine offline scenarios
evals/, redteam/       quality lane
baseline/              frozen        v1, the single-agent baseline
```

## 12. Design not yet in the code

| Design | Code today | Where to look |
|---|---|---|
| `human_review` as a LangGraph interrupt with checkpoints | The graph compiles without a checkpointer; state lives in the runner's memory; the review queue decides outside the graph | `agents/graph.py`, `agents/runner.py`; `checkpoints_db` and `langgraph-checkpoint-sqlite` are unused |
| $0.10 per-conversation cost budget | Defined (`MAX_COST_MICROS_PER_CONVERSATION`) but nothing adds model cost to it | `contracts/state.py`, `agents/runner.py` |
| `python -m agents.audit <conversation_id>` rebuilds a conversation | No such command; `SqliteAuditLog.read` and `verify_chain` exist | `data/store/audit.py` |
| `case` and `respond` written by Haiku | Both are code; `models.yaml` still lists `case` and `transaction`, and `prompts/respond.md` is not loaded | `agents/config/models.yaml` |
| Case opened through the `create_case` tool | The case node writes the store directly | `agents/nodes/case.py` |

## 13. Bullets against this design

| Bullet | Status | Nodes and stores it brought to life |
|---|---|---|
| B1 | built | `intake`, `concierge`, `knowledge`, `respond`; knowledge index; tool registry; contract validation; one audit row; chat UI |
| B2 | built | `identity_gate`, `account`, `case` (lockout); `identity` split; credential masking; clock; login and step-up (ADR 0007) |
| B3 | built | `transaction`, `confirm`, `rules`, `compliance`, `approval`, `execute`; proposals, approvals, ledger, audit triggers |
| B4 | built | case packets, review queue and `AgentReviewDesk`, "Your cases", superseded document version |
| B5 | partly | Budgets (not cost), fail-closed edges, kill switch and D-07 flags built; audit rebuild command and cost budget open (§12) |
