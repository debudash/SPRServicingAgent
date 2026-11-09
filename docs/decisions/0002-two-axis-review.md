# 0002. Two-axis code review, AI-assisted, human-approved

Date: 2026-11-09 · Status: accepted · Decided by: integrator (owner) · Issue: #12

## Context
Until now the only review in the pipeline was `verdict`, the independent Claude review that gates agent
PRs (`agent/...` branches). Human PRs had no review step beyond CI. The first B0 PRs merged that way:

| PR | What it changed | Review it had |
|---|---|---|
| #2 | Wave 0: layout, CI, night-shift kit, protected paths, `contracts/` stub, CLAUDE.md | CI only |
| #7 | The PRD | CI only, plus the owner answering the decision questions |
| #9 | Switch to tracer bullets (ADR 0001) | CI only |
| #11 | Eval spec, including the golden answer key in `evals/golden/` | CI and the answer-key integrity test only |

These were human PRs written with an AI assistant and checked only by the same assistant and CI.
Nothing independent asked whether they met the repo's standards or matched what their issue asked for.
For documents that was a tolerable gap. For `contracts/` (what every lane builds against), `evals/golden/`
(what every change is graded against) and the money path, it is not: a defect there spreads into every
lane, or grades every later change against a mistake. #11 is the clearest example, because it changed the
golden set.

Workstream F of the brief also asks for evidence that review catches real defects, which a pipeline with
no human-PR review cannot produce.

## Decision
Review has two axes, done by AI, approved by a human:

- **Standards:** does the change follow CLAUDE.md, AGENT_RULES.md and the coding standards in the repo?
- **Spec:** does it do what its issue and the PRD asked, and nothing else?

`/code-review` runs both axes in parallel and reports them side by side. Who reviews what:

| PR | Review before merge |
|---|---|
| Agent PR | `verdict` (automatic, required check) |
| Agent PR touching the money path | `verdict` plus a human-run `/code-review` spot-check |
| Human PR touching `contracts/`, `evals/golden/` or the money path | `/code-review`, findings posted as a PR comment |
| Any other human PR | Not required; the reason is stated in the PR template |

Every real defect a review finds goes through the bug workflow: an issue, a failing test, the fix, and a
row in `docs/ISSUE_LOG.md` naming the PR where it was found.

## Consequences
- The gap that let #2, #7, #9 and #11 merge unreviewed is closed for the paths where it matters. Pure
  documentation and planning PRs still merge on CI alone, but must say so in "Reviewed by".
- The rule is written in three places that must stay in step: CLAUDE.md (summary), AGENT_RULES.md (the
  table) and this ADR (the reasons).
- **Auto-merge limits the spot-check.** Night-shift PRs merge as soon as `test` and `verdict` pass, so a
  spot-check on a money-path agent PR could arrive after the merge. Until a mechanical guard exists,
  money-path tickets are never labelled `night-safe`, so the night shift never opens a money-path PR.
  Money-path work is done by day, where it falls under the human-PR rule.
- Review findings become measurable: the issue log's "Found by" column counts defects found per review.

## Alternatives rejected
- **Review every PR.** Costs time on documentation PRs and teaches people to skim the review.
- **Required GitHub approvals.** Both simulated developers share one GitHub account, and GitHub does not
  let an author approve their own PR, so a required approval would block every merge.
- **Rely on `verdict` alone.** It only runs on agent branches, and it judges a diff against its ticket.
  It does not check repo standards across a human design change.

## Open
- **Retrospective review of #11.** It changed `evals/golden/` before this rule existed. Running
  `/code-review` over it would bring the answer key under the rule it now falls under.
- **A mechanical money-path guard** (a CI check that blocks auto-merge when an agent PR touches
  money-path files without a spot-check label) can replace the "never night-safe" rule once the
  money-path folders exist (B2 onward).
