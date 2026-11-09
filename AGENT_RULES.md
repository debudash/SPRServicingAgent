# Agent coordination rules

CLAUDE.md points here. It applies to every agent, day or night, on every teammate's machine.

## Lanes and ownership
- Every issue has exactly one `lane:<name>` label. Work only on issues in your lane.
- Each lane owns the folders listed in the table below. Edit files outside your lane only when the ticket names them.
- Shared files (the integrator paths in the table) belong to the integrator. Agents never change them: comment the exact change needed on the issue and add `needs-human`.

| Lane | Developer | Owns |
|---|---|---|
| `data` | Dev A | `data/` |
| `agents` | Dev B | `agents/` |
| `quality` | Dev A | `evals/` (except `evals/golden/`), `redteam/` |
| integrator (a human, no agent lane) | you | `contracts/`, `evals/golden/`, `baseline/`, `docs/`, `.github/`, `CLAUDE.md`, `AGENT_RULES.md`, `requirements*.txt`, `pyproject.toml`, `Makefile`, `Dockerfile`, `compose.yaml` |

Two simulated developers share one GitHub account and are told apart by lane label, branch name and
commit author ("Dev A agent (data lane)"). Each has their own Claude token (`CLAUDE_TOKEN_DEVA`,
`CLAUDE_TOKEN_DEVB`). The `quality` lane grades and attacks what the `agents` lane builds, so the
checker is never the builder.

Agent PRs that touch an integrator path are rejected automatically by the publish job.

## Branches and PRs
- One issue = one branch = one PR. Branch name: `agent/<lane>/issue-<n>` for agents, `<who>/issue-<n>` for humans (`integrator/`, `deva/`, `devb/`).
- Never push to `main`. Every change lands through a PR whose checks pass (`test` and, for agent PRs, `verdict`).
- PR body starts with `Closes #<n>`.

## Who reviews what
Two-axis review (ADR 0002): **standards** (does it follow CLAUDE.md and this file?) and **spec** (does it do
what the issue and PRD asked?). AI does the review; a human approves the merge.

| PR | Review before merge |
|---|---|
| Agent PR (`agent/...`) | `verdict`, the automatic independent review. Required check. |
| Agent PR touching the money path | `verdict`, plus a human-run `/code-review` spot-check. Night-shift PRs auto-merge, so money-path tickets are never labelled `night-safe` (see Night shift). |
| Human PR touching `contracts/`, `evals/golden/` or the money path | `/code-review`, with its findings posted as a PR comment before merge. |
| Any other human PR | Not required. Say why in the PR template's "Reviewed by" section. |

**Money path** means code that quotes, executes or approves a withdrawal, or decides identity: quote
calculation, execution, approval tokens, the rule engine, Compliance decisions, the human approval path and
the identity gates (bullets B2 to B4).

Every real defect a review finds becomes a bug issue and goes through the bug workflow in CLAUDE.md
(failing test first, then the fix, then a row in `docs/ISSUE_LOG.md` with "found by: review on PR #n").

## Contracts first
- Wave 0 merges the interfaces, stubs and contract tests before any lane starts. After that, only the integrator changes them, through a human PR that bumps `CONTRACTS_VERSION`.
- Build against the contract, not against another lane's implementation.

## Talking to other lanes
- Only through issue comments and labels. Stuck on another lane: comment on the blocking issue, mention its lane, add `blocked` to yours.
- A product or design question you cannot decide: comment the exact question on the issue and add `needs-human`.

## Definition of done
- Tests written or updated for the change, and the full suite passes locally.
- One line in a new file `progress/<lane>/<YYYY-MM-DD>-issue-<n>.md` (one file per change, so parallel PRs never conflict): date, lane, issue, what changed. Never append to a shared progress file.
- A failure seen twice becomes a new rule in this file. Agents propose the rule in their PR summary; a human adds it.

## Night shift
- Only issues labeled `night-safe` run unattended. Label only tickets with clear acceptance criteria and no open design questions.
- Never label a money-path ticket `night-safe`: night-shift PRs auto-merge, which would skip the money-path spot-check.
- If `main` is red, every lane except `FIX_LANE` stops taking work until it is green.
- Kill switch: set the repo variable `AGENTS_ENABLED` to `false`.
