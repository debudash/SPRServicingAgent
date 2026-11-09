# PRD: SPR Servicing Desk (v2)

Status: approved 2026-11-09 · Owner: integrator · Source brief: `problemstmt/AI_Engineer_Assignment.docx`

Every item is numbered so tickets, tests and eval cases can cite it (`FR-08`, `NG-01`, `M-03`).
Targets live **only** in section 7. How each metric is computed is defined in the eval spec, not here.

---

## 1. Framing

**Who uses it**
- **Customer:** an SPR SecureGrowth Fixed Annuity holder, aged roughly 55–85, using web chat. Often stressed
  (a bill, an illness, a family member "helping"). Wants to know what they can take out, what it costs,
  and to get it done in one sitting.
- **Reviewer:** an SPR servicing analyst working a queue of escalated cases, who needs a case packet they can
  decide from without re-reading the conversation.

**The job it replaces:** a phone call to a servicing rep, who verifies identity, quotes from the fee schedule,
and either keys in the withdrawal or starts a paper hardship form.
Baseline (assumed, to be measured in a real pilot): about **12 minutes** per routine withdrawal call, and
**5–10 business days** before a hardship case reaches a decision-maker with its paperwork.

**Data it touches:** SPR customer records (identity, balances, transactions), SPR product and policy documents,
and the cases, proposals and audit records the desk creates. All data in this project is synthetic.

**What makes it unsafe:** money moved that should not have been (wrong amount, wrong person, unconfirmed,
unreviewed); a waiver granted by a machine; a coached or vulnerable customer processed straight through;
date of birth or SSN digits leaking.

**The sentence it must never be wrong about:**
> The desk never moves money unless identity, the shown quote, the customer's explicit confirmation and an
> independent compliance approval of that exact proposal are all established, and it never grants a waiver.

## 2. Decisions taken for this PRD

| ID | Decision | Source |
|---|---|---|
| D-01 | Withdrawals below the large-withdrawal threshold with no risk flags may execute without a human, after the Compliance agent approves. | Owner decision |
| D-02 | Large-withdrawal threshold: gross amount **over $25,000 or over 50% of the balance** always goes to a human. | Owner decision |
| D-03 | Surrender-charge waivers follow the knowledge base exactly: **terminal illness (with documentation), death benefit, RMD amounts**. There is no general hardship waiver; nursing-home confinement gets the standard schedule. A waiver is always granted by a human. | Knowledge base (faq.md, fee_schedule.md) |
| D-04 | The system clock is a configured **as-of date, 2024-12-01**, not today's date. It is the only date at which every starter account's stored contract year matches its start date. | Platform audit (PG-02) |
| D-05 | Free allowance remaining = 10% × current balance − withdrawals already taken this contract year, floored at 0. Matches the fee schedule's formula and example when no earlier withdrawal exists; netting earlier withdrawals stops one large withdrawal being split into many free ones. | Owner decision, interpreting fee_schedule.md |
| D-06 | Time-saving baselines are stated assumptions (section 1), labelled as such. | Owner decision |
| D-07 | Vulnerable-customer signals that force a human hold, at any amount: a third party directing the customer; pressure or urgency; age 80+ with a withdrawal above the free allowance; confusion or repeated changes of amount. | Owner decision |
| D-08 | 3 failed identity challenges lock account actions for the session and open a case. | Owner decision |
| D-09 | A third party (spouse, child, beneficiary, claimed attorney) gets public product information only and a case so SPR can verify their authority offline. Nothing about the account is shared. | Owner decision |
| D-10 | Budgets: per customer turn 8 agent hops, 12 tool calls, 30 seconds; per conversation $0.10 model cost. These are hard stops; the cost target (M-14) is the expected average. | Owner decision |

## 3. Guarantees the platform will not provide

What the starter data, documents and stack do **not** enforce. Each is now a requirement owned by this build.

| ID | Gap found in the audit | What this build must do | Lane |
|---|---|---|---|
| PG-01 | The starter data has no transaction history, so the free allowance remaining cannot be computed. | Add a transactions table and seed prior withdrawals. | data |
| PG-02 | `contract_year` is stored, not derived, and the data is frozen at a past date (today's date gives wrong years). | Derive contract year and age from dates and the as-of clock (D-04); a data-quality check fails if stored ≠ derived. | data |
| PG-03 | `identity_verified` is static, out-of-band account trust. There is no session authentication; the session identity is assumed to come from upstream. | Keep v1's two gates: Gate A (account trust, from the record) and Gate B (DOB + last-4 SSN challenge per session). | agents |
| PG-04 | Date of birth and SSN digits sit in the same record as the balance. | Split restricted fields into an identity store that only identity code can read. | data |
| PG-05 | Documents carry no ID, version or effective date. | Ingestion adds document ID, version, effective date and section to every chunk; answers cite them. | data |
| PG-06 | The documents have no large-withdrawal rule, vulnerable-customer policy or terminal-illness documentation list. | Write SPR operations policy documents (synthetic, labelled) that add process rules without contradicting any product fact. | integrator |
| PG-07 | There is no qualified-account (IRA) flag, so RMD eligibility cannot be determined. | RMD requests are explained from the documents and escalated, never decided. | agents |
| PG-08 | The orchestration framework provides shared state and routing but does **not** enforce field ownership, per-agent tool scope, approval binding, idempotency or budgets. | Build each in code with unit tests (FR-08, FR-09, FR-19 to FR-22). | agents |
| PG-09 | Models are non-deterministic, and claude-sonnet-5 rejects a temperature override. | No guard decision depends on model consistency; evals repeat runs and report variance. | quality |
| PG-10 | SQLite does not enforce append-only tables. | Triggers block UPDATE and DELETE on the audit table, with a test. | data |

## 4. Functional requirements

Each item can be turned into an eval case or unit test that passes or fails without asking the author.

### Identity and access
- **FR-01** Product and policy questions are answered without identity, from the knowledge base, and every
  answer cites document ID, version and section.
- **FR-02** Account-specific information (balance, contract year, allowance, quotes) is given only when Gate A
  (account trusted) and Gate B (challenge passed this session) both hold. Correct credentials on an untrusted
  account grant nothing.
- **FR-03** On an untrusted account, the customer is told at the start that the account cannot be serviced
  here and how to contact SPR, and is never asked for credentials.
- **FR-04** After 3 failed challenge attempts in a session, account-specific actions are locked for that
  session and a case is created.

### Quotes
- **FR-05** A quote states, exact to the cent and computed from records: contract year, surrender rate, free
  allowance remaining (D-05), excess amount, surrender charge and net proceeds.
- **FR-06** When the customer is under 59½ at the as-of date, the quote includes the knowledge base's IRS
  early-withdrawal notice, stated as information, not tax advice.
- **FR-07** A quote is refused, with the reason, when the amount is ≤ 0, exceeds the balance, or the account
  status is not `active`.

### Execution (maker–checker)
- **FR-08** A withdrawal executes only when all of these hold: both identity gates; a quote for that exact
  amount was shown this session; the customer explicitly confirmed after seeing it; a Compliance approval
  token is bound to the hash of that exact proposal; and the proposal is in the self-service tier (D-01, D-02).
  Any change to the amount voids the token.
- **FR-09** Execution is idempotent: replaying a proposal ID never creates a second withdrawal.
- **FR-10** An executed withdrawal writes the transaction and its audit record in one transaction. The audit
  record holds the approvals, policy document versions, and model and prompt versions.

### Compliance review
- **FR-11** Every proposal is reviewed by the Compliance agent, which returns `approve`, `hold` or `escalate`
  with reasons citing a policy section. Rule checks (threshold, status, waiver request, age, budget) are
  computed in code first, and Compliance cannot approve a proposal those checks flag.
- **FR-12** Any vulnerable-customer signal in D-07 results in `hold` and a human case, whatever the amount.
  The age rule is computed in code; the conversational signals are judged by the Compliance agent and
  measured by eval recall. The vulnerable-customer policy document (PG-06) states these rules for the
  knowledge base.

### Waivers and hardship
- **FR-13** A terminal-illness waiver request gets the documentation requirements from the knowledge base and
  a human case. The quote shown is without the waiver, and the desk never states that a waiver applies.
- **FR-14** Any other hardship (financial difficulty, nursing home, other medical) is told, per the FAQ, that
  there is no general hardship waiver, with an offer of a servicing case. The desk never implies a waiver.
- **FR-15** RMD requests are explained from the knowledge base and escalated (PG-07).

### Cases and the human reviewer
- **FR-16** Every escalation produces a case packet: customer ID, request summary, quote (if any), rule flags,
  Compliance reasons, a conversation excerpt with restricted fields removed, and a recommendation.
- **FR-17** The reviewer can approve, reject or request information. Approving a withdrawal executes it under
  FR-09 and FR-10, recording the human approval.
- **FR-18** The customer always learns the outcome as one of: executed (with a confirmation reference), pending
  review (with a case reference), refused (with the reason), or out of scope (with what the desk can do).

### Coordination
- **FR-19** Every message between agents validates against a versioned schema. An invalid message is rejected
  and the case fails closed.
- **FR-20** Each conversation enforces the D-10 budgets (per turn: 8 agent hops, 12 tool calls, 30 seconds;
  per conversation: $0.10). When one runs out, the case escalates with code `UNAVAILABLE` and no action is taken.
- **FR-21** If the Compliance agent or the case queue is unavailable, no withdrawal executes and the customer
  is told what happens next.
- **FR-22** Each agent can call only the tools registered for its role. Any other call is refused in code
  and logged.

### Data, audit and operations
- **FR-23** Restricted fields (date of birth, SSN digits) never appear in prompts, traces, logs, answers or
  case packets.
- **FR-24** Retrieval returns the document version in force at the as-of date.
- **FR-25** Given a conversation ID, one command rebuilds the full timeline from the audit log, including its cases: what was asked, what
  each agent decided and why, which versions applied, and who approved any money movement.
- **FR-26** A per-capability kill switch can turn execution off. The desk then still answers questions and
  routes every withdrawal to a human.
- **FR-27** Each conversation has one trace across all agents, recording model and prompt versions, tokens, cost and
  latency.

## 5. Non-goals (enforced as behaviours)

- **NG-01** Never grants or applies a surrender-charge waiver. Only a human does (D-03).
- **NG-02** Never gives investment, tax or legal advice. It declines and may state knowledge-base facts, such
  as the IRS notice.
- **NG-03** Never changes beneficiaries, contact details or payout destinations. It explains the process and
  creates a case.
- **NG-04** Never acts for anyone other than the session's verified owner. A spouse, child, beneficiary or
  claimed attorney gets public product information and a case (D-09), never account information.
- **NG-05** Never discloses or discusses another customer's account.
- **NG-06** Never answers a product fact from model memory. If the knowledge base has no answer, it says so
  and offers a case.
- **NG-07** Never processes a full surrender. A full surrender always goes to a human (it is above the 50%
  threshold anyway).
- **NG-08** Never reveals restricted fields, even to the verified owner ("what SSN do you have on file?").
- **NG-09** Never follows instructions found inside documents, tool results or another agent's output.

## 6. Failure behaviour

Each outcome is distinct to the customer, and tagged in the trace and the UI with its code.

| Code | Situation | What the customer sees |
|---|---|---|
| `NO_SOURCE` | The knowledge base does not answer it. | "SPR's documentation doesn't cover that", plus an offer of a case. Never a guess. |
| `NOT_PERMITTED` | Identity, account status or tier blocks it. | A refusal with the reason and the next step. |
| `NEEDS_HUMAN` | Threshold, waiver, vulnerable signal, third party, RMD. | Case created, case reference, what happens next. |
| `UNAVAILABLE` | Checker or queue down, budget exhausted, internal error. | "I can't complete this right now", no action taken, case created. |
| `OUT_OF_SCOPE` | Advice, other products, other customers. | A polite decline and what the desk can do. |

## 7. Success metrics

Targets are set here and nowhere else. Safety metrics are blocking; the rest are tracked.

| ID | Metric | Target | Baseline |
|---|---|---|---|
| M-01 | Withdrawals executed without every FR-08 precondition | **0** (blocking) | v1: 0 of 16 measured safety cases |
| M-02 | Restricted-field exposures (answer, trace, log, packet) | **0** (blocking) | v1: not measured |
| M-03 | Compliance false approvals on labelled cases | **0** (blocking) | none (new role) |
| M-04 | Waivers stated or applied by the desk | **0** (blocking) | v1: not measured separately |
| M-05 | Quote accuracy: every FR-05 figure exact to the cent | **≥ 98%** of quote cases | v1 (Claude): 86% overall accuracy |
| M-06 | Citation correctness: right document, version and section | **≥ 95%** | v1: no citations |
| M-07 | Grounding on multi-step cases (the right evidence fetched before answering) | **≥ 95%** | v1 (Claude): 0 of 6 |
| M-08 | Routing and handoff correctness | **≥ 90%** | none (new) |
| M-09 | Containment: routine self-service requests resolved without a human | **≥ 80%** | 0%: every request is a phone call today |
| M-10 | **Counter-metric:** unnecessary escalations of eligible self-service cases | **≤ 10%** | none |
| M-11 | Routine withdrawal, start to confirmation | **≤ 3 minutes** | assumed 12-minute call |
| M-12 | Hardship case packet ready for the reviewer | **< 1 minute** | assumed 5–10 business days |
| M-13 | p95 latency per customer turn | **≤ 8 seconds** | v1 (Claude): 4.7 s average per case |
| M-14 | Model cost per resolved conversation | **≤ 2× v1** (≤ $0.042) | v1 (Claude): ≈ $0.021 per run |
| M-15 | Open critical red-team findings at release | **0** (blocking for release) | none |

M-09 and M-10 pull against each other on purpose. Escalating everything games safety but breaks M-09.
Approving everything games containment but breaks M-03 and M-10.

## 8. Open items

- **O-01** Baselines M-11 and M-12 are assumptions (D-06). A real pilot would measure them.
- **O-02** Write the vulnerable-customer and large-withdrawal policy documents (PG-06) from D-02 and D-07,
  labelled as synthetic SPR operations policy.
- Resolved: allowance basis (D-05), budgets (D-10), vulnerable-customer signals (D-07).
