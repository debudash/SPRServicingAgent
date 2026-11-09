# Delivery plan: tracer bullets

Why bullets instead of layered milestones: [ADR 0001](decisions/0001-tracer-bullets-over-layered-milestones.md).
Requirement IDs refer to [PRD.md](PRD.md).

Each bullet is one wave (`wave:<n>` label) and one GitHub milestone. It starts with the integrator freezing
the bullet's contracts (a human PR), then the three lanes build in parallel:

- `data` (Dev A): the records and documents the path needs
- `agents` (Dev B): the agents, tools and UI for the path
- `quality` (Dev A): the bullet's eval cases and attack cases, written alongside the features

A bullet is done when its exit criterion holds on `main`, its eval cases pass, and it can be demonstrated in
the Docker stack.

| Bullet | Customer path | PRD items | Exit criterion |
|---|---|---|---|
| **B0** Foundation and framing | (none yet) | — | Repo, CI and night shift green; PRD, eval spec, blueprint, first ADRs. |
| **B1** Cited product answer | "What's the surrender charge in year 5?" gets a cited answer | FR-01, FR-19, FR-24, FR-27, NG-06, NG-09 | Concierge → Knowledge → cited answer, with one trace and one audit row; chat UI in Docker; first eval cases passing. |
| **B2** Identity and account view | A verified customer sees their balance; an untrusted one is turned away | FR-02, FR-03, FR-04, FR-23, NG-05, NG-08, D-08 | Identity store split; both gates and the lockout enforced in code; restricted-field guard tested. |
| **B3** Routine withdrawal | Quote → confirm → Compliance approves → executes | FR-05 to FR-11, FR-22, D-01, D-05 | Transactions and allowance; Transaction and Compliance agents; approval token bound to the proposal; idempotent execution; append-only audit. |
| **B4** Human review path | A large or waiver-related request reaches a reviewer who decides | FR-13 to FR-18, D-02, D-03, NG-01, NG-07 | Case agent and case packet; review-queue UI; human approval executes through the same path as B3. |
| **B5** Hard cases and failure modes | Vulnerable customer, third party, budget exhausted, checker down, kill switch | FR-12, FR-20, FR-21, FR-25, FR-26, D-07, D-09, D-10, NG-02 to NG-04 | Every failure code in PRD §6 reachable and tested; audit rebuild command works. |
| **H** Hardening | (none new) | M-15, workstreams H, I, J | Red-team campaign and regression suite; model-per-role evals; dashboard; game day run. |
| **R** Release and evidence | (none new) | all M-xx | Deployment recommendation, evidence pack, README, presentation. |

Paid LLM evals (manual `evals` workflow) run at the end of **B3**, at the end of **B5**, and before **R**.
