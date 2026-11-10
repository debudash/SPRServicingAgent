# 0007. Sessions start at a login; a step-up check guards money

Date: 2026-11-10 · Status: accepted · Decided by: integrator (owner) · Issue: #78

Supersedes this ADR's first draft ("the identity check masks the bound customer's own stored values").
Narrows ADR 0005: credential capture from chat text becomes a backstop, no longer the way in.

## Context
In B2 the customer proves who they are by typing their date of birth and SSN last four into the chat
(ADR 0005). Code captures and masks them, but chat text is a poor channel for secrets:

- **The red team (#60) found a gap.** A bare "7823" with nothing around it can't be told apart from an
  amount, so the customer's own last four can reach the model. GR-09 and FR-23 make no exception for who
  typed it.
- **The first draft of this ADR closed the gap by masking the customer's own stored values on every turn.**
  Review found that this creates a guessing oracle. Before verifying, an impersonator can send amounts or
  dates and watch for the turn where the desk behaves differently. That reveals the last four or the date
  of birth without ever touching the three-attempt challenge.
- **Practice moved on.** Contact centres and chat platforms collect secrets in a separate masked input
  (keypad masking, secure forms), never in the conversation. Free-text redaction is kept only as a
  backstop.

The brief settles where authentication belongs: *"Customer authentication is handled upstream: trust the
session identity, not the customer's intent."* It still asks the desk for *"both identity gates, lockout
and the restricted-field guard"*.

## Decision
1. **A login page starts every customer session.** It has a dropdown of customers and a password field,
   standing in for the upstream authentication the brief assumes.
   - Passwords are dummy demo values, stored only as salted hashes (`hashlib.scrypt`) in a `logins` table
     owned by `data/identity`. They are never shown, logged or sent to a model.
   - A successful login binds the session to that customer, as the "Signed in as" dropdown does today.
   - A wrong password is refused at the login page. Password lockout is the upstream system's job and is
     not built here.
2. **Gate A stays in the agent flow, unchanged.** An account whose `identity_verified` is false (Raymond,
   SPR-1002) can log in but is turned away from every account action, with the contact number (GR-14).
3. **Gate B becomes a step-up before money moves.** The customer can ask questions and see their account
   view on the strength of the login.
   - When a withdrawal is confirmed (after the quote and the explicit yes, GR-17), and before rules,
     Compliance or approval, the desk asks for date of birth and SSN last four.
   - The UI collects them in a **masked form, outside the chat**. The form posts straight to the identity
     check through the runner; the values never become turn text.
   - A pass is good for the rest of the session.
4. **Lockout is unchanged (D-08).** Three failed step-ups lock the session and open a case. The correct
   answer afterwards does not unlock it.
5. **Pattern masking stays as the backstop (ADR 0005, narrowed).** Customers still type dates and SSN
   digits unprompted, and the brief's attack library includes extracting restricted fields. The runner
   still masks every turn before anything sees it. It no longer feeds the challenge.
6. **The next contracts version.** It adds:
   - `DeskRunner.login(customer_id, password) -> str | LoginRefused`, replacing `start` for customers.
     A guest session for product questions is kept, see open item 1.
   - `DeskRunner.step_up(conversation_id, dob, last4) -> GateResult`.
   - A state field saying a step-up is pending, so the UI knows to show the form.

   The first draft's `IdentityCheck.mask_stored` is dropped.

## Consequences
- **Credentials never travel in chat text on the designed path,** so the stored-value gap and the oracle
  both go away instead of being patched. What remains is incidental typing, which the backstop handles.
- **The demo flow matches how banks work:** log in, look around, re-verify to move money.
- **The golden cases change.** This is the owner's edit, a change to the spec, not tests bent to fit code.
  - The B2 cases that verify through chat turns (BH-B2-01, BH-B2-02, the G-B2 challenge cases) are
    rewritten.
  - A balance needs only the login (and Gate A).
  - Lockout is exercised through three failed step-ups at confirmation.
  - The case schema gains a `step_up:` step and a logged-in session setup.
- **Code that retires:** the challenge parts of `identity_gate`'s chat path (ASK on account intents, and
  reading candidates from the turn), with their tests and the red-team cases built on them. Login and
  step-up tests replace them. Gate A, lockout, cases, third-party handling (D-09) and the masking backstop
  stay.
- **Ordering.** This lands before #88 (confirm), because confirmation is where the step-up sits; #88 and
  #89 build on it.

## Planned: the behaviour-demo page (after #91)
v1's "Behaviour demo" page carries over, rebuilt on the eval assets so the demo and the evals cannot
disagree:

- **Scenarios are case IDs** from `evals/golden`, run through the real desk and checked by
  `evals/score.py`, with no judge.
- **The default mode is replay**: the recorded results of the last milestone eval run, free and the same
  every time. A **live** button runs the same scenarios against the model.
- **Each card shows** the turns and replies, the outcome, the nodes and tools in order, the guard that
  fired, and for money scenarios the ledger and audit rows the run wrote.
- **Each run uses a scratch database**, so the live chat's data is untouched.
- **It is also a terminal command**, `python -m evals.demo`, with a non-zero exit on failure.

Scenarios:
1. Cited product answer.
2. Raymond turned away (Gate A).
3. Margaret's balance (login, then the account view).
4. The full money path: quote, yes, step-up, Compliance, execution.
5. The amount changed after the quote.
6. Prompt injection asking to "execute now".
7. A large withdrawal escalated to a human. The reviewer's decision (approve, then execute as
   `human:<reviewer>`) is added after B4.
8. Three failed step-ups: lockout and a case.
9. Kill switch on: a confirmed withdrawal goes to a human (FR-26).

## Owner decisions (2026-11-10)
1. **Guest access is kept.** The login page has a "Continue without logging in" link. A guest session
   answers product questions, and a third party there is told the owner must contact SPR (D-09).
2. **A step-up lasts for the session.** Once passed, later withdrawals in the same session don't ask
   again. The lockout still counts failures across the session.

## Alternatives rejected
- **Mask the bound customer's own stored values on every turn** (this ADR's first draft). It creates the
  guessing oracle above and still can't let the customer use that number as an amount.
- **Login replaces Gate B entirely.** It is simpler, but the desk would no longer run the second gate or
  the lockout the brief lists for B2.
- **Keep the challenge in chat and add a secure form only as an option.** It leaves two ways in to test
  and attack, and the chat way keeps the gap.
- **One-time codes to the phone or email on file.** This is the production direction, since NIST
  SP 800-63 moved away from knowledge-based checks, but the starter kit's challenge data is date of birth
  and last four. It goes on a slide as the production story.
