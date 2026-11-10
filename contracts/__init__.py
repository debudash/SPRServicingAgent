"""Typed interfaces between lanes: outcomes, roles and tools, money, classification,
messages and state.

Owned by the integrator (a human). Agent PRs that touch this folder are rejected by the
pipeline. Lanes build against these contracts, never against each other's code.
Sources: docs/blueprint/README.md and docs/ARCHITECTURE.md. Every change bumps
CONTRACTS_VERSION and is additive (ADR 0001): new fields and messages only, never changed
or removed ones.

The one exception so far is 0.4.0 (owner decision, issue #80): `CasePacket.customer_id` became
required, a tightening made before any case had been stored.

0.6.0 (ADR 0007) adds the login and step-up ports beside the B2 ones, and makes one owner-approved
change: the account-view rule *relaxes* to Gate A and (a login or Gate B), with the lock named
(#107). Nothing that validated before is refused, except states no flow produces (#108).
The next version tightens them (an account view needs a login, the step-up needs a login, `start`
is for guests only) once the lanes comply (#102, #103), the same way 0.4.0 was made.

0.6.1 (#89) is additive: `CaseReason.WITHDRAWAL_REVIEW`, the case for a withdrawal a person must
review, which always names its proposal and carries its quote; three optional `CasePacket` fields
(`proposal_id`, `compliance_decision`, `signals`) for the B4 reviewer; and `RuleFlag.OPEN_REVIEW`
(#136), a withdrawal in this conversation is already with a person.
"""

CONTRACTS_VERSION = "0.6.1"
