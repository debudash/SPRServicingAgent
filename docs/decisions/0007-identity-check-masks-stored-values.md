# 0007. The identity check masks the bound customer's own stored values

Date: 2026-11-09 · Status: **proposed** · Decided by: integrator (owner) · Issue: #78

## Context
ADR 0005 masks credentials by pattern, at the runner's entry, before anything sees the turn. Patterns need
context. A date of birth, an SSN word, an open challenge or a spaced or spelled run all mark four digits
as a credential. A plain four-digit group with none of these is left alone, because it may be an amount
("take out 2000") or a year.

The red team (#60) found where that leaves a gap. A verified customer who sends "7823" on its own, with no
challenge open, sends their real SSN last four to the Concierge model, the transcript and the checkpoint.
It is their own value, typed by them, but GR-09 and FR-23 say a restricted value never appears in a prompt,
trace or log, whoever typed it. Patterns cannot close this: "7823" and "2000" have the same shape. Only the
identity store knows which four digits are this customer's.

## Decision (proposed)
- **A second port method.** `IdentityCheck.mask_stored(customer_id: str, text: str) -> str` returns `text`
  with the customer's own stored date of birth and SSN last four replaced by `[DOB]` and `[SSN-4]`. It
  matches the same forms the red-team detector does: the last four as digits, spaced or spelled, and the
  date in the formats `capture` reads. Like `check_challenge`, the stored values never leave the call.
  Only the masked text comes back.
- **Called after `capture`, on every turn of a bound session.** The runner masks the turn with
  `capture`, then with `mask_stored` for the session's customer, before the transcript is written. The
  case node passes its excerpt through `mask_stored` for the case's customer. Every case has one (contracts
  0.4.0).
- **Pattern capture stays.** It is still the only thing that finds credential candidates for the
  challenge. It also masks other people's values typed into the session, and values typed before a
  customer is bound. `mask_stored` is the backstop for the bound customer's own values.
- **Contracts 0.5.0.** The port gains the method, with a contract test. `data/identity` implements it, and
  the restricted-field property suite (#60) gains the "plain digits after verifying" attack.

## Consequences
- **The documented gap closes.** The bound customer's own values never reach a model in any form the
  matcher knows.
- **An amount that equals the customer's last four is masked.** "Withdraw 7823 dollars" from that customer
  becomes "Withdraw [SSN-4] dollars", and the desk asks for the amount again. This is deliberate, and
  consistent with ADR 0005: a needless mask costs a retry, a miss leaks. Money-shaped text (`$7,823.00`)
  could be exempted, but then the value leaks whenever it is typed as money. **Owner decision:** mask
  always (recommended), or exempt money-shaped text.
- **One extra store read per turn**, for bound sessions only. It is a single-row lookup, cheap next to a
  model call.
- **The identity module's surface grows from two functions to three.** The isolation test (no other module
  names the identity table) is unchanged.
- **Not covered: another customer's values typed with no context** ("my brother's is 3367"). Pattern
  capture still handles those only in credential context. Masking every customer's values on every turn
  would mean a scan over the whole identity table. That is possible at four customers, but not a design to
  carry to production.

## Alternatives rejected
- **Mask every bare four-digit group in a verified session.** Simple, but it breaks amounts ("take out
  2000"), which B3 depends on, for every customer and on every turn, to catch a rare re-send.
- **Return the stored values to the runner to match against.** The runner would hold restricted values
  in memory and could log them. That is exactly what ADR 0005 keeps inside `data/identity`.
- **Accept the gap.** It is the customer's own value, but GR-09 makes no exception for who typed it, and
  the checkpoint keeps it.
