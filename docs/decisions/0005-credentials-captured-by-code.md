# 0005. Typed credentials are captured by code and never reach a model

Date: 2026-11-09 · Status: accepted · Decided by: integrator (owner) · Issue: #17

## Context
The blueprint (#16) gave the Concierge a `verify_identity` tool that "passes credentials to the identity
gate, never sees stored values". Writing the architecture flows showed the gap: customers type their date of
birth and the last four digits of their SSN into the chat (golden case BH-B2-02 does exactly that). Any model
that reads that turn has seen restricted values, and so would the checkpoint store and the trace. That breaks
GR-09 and FR-23, whatever the tool does with the values afterwards.

## Decision
- **`intake` extracts, then masks.** Before any model, checkpoint or trace sees a customer turn, code
  pulls out credential-shaped text (a date, a 4-digit group near "SSN" or "last four") and hands the
  candidates to `identity_gate` in memory. The turn is then masked (`[DOB]`, `[SSN-4]`) and only the masked
  text moves on.
- **The Concierge has no identity tool.** It never handles credentials. The trace still records a
  `verify_identity` step (from `identity_gate`), so the eval cases that expect that step are unchanged.
- **The check is a function, not a read.** `data/identity.check_challenge(customer_id, dob, last4)` returns a
  boolean; stored values never leave it.

## Consequences
- GR-09 can be tested as a property: no restricted value of the starter or synthetic customers may appear in
  any prompt, checkpoint, trace or audit payload in any eval run.
- Extraction is pattern-based, so a customer who writes a date in an unusual form may fail the challenge
  and be asked again. That costs a retry, and with a 3-attempt lockout (D-08) a misparse must not count as
  a failed attempt: a turn with no recognisable candidates asks again without counting.
- The red team gets a specific target: credentials smuggled past the extractor (spelled out, split across
  turns) must still never reach a model unmasked, or must be caught by the scrubber's second pass.

## Alternatives rejected
- **Let the Concierge read the credentials and call a tool.** Simple, but the model, the checkpoint and the
  trace all see restricted values.
- **A separate verification form only.** Cleaner, but customers type credentials into chat anyway, so the
  chat path needs the extractor regardless. A form can be added to the UI later as a convenience.
