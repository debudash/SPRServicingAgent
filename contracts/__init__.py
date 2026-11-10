"""Typed interfaces between lanes: outcomes, roles and tools, money, classification,
messages and state.

Owned by the integrator (a human). Agent PRs that touch this folder are rejected by the
pipeline. Lanes build against these contracts, never against each other's code.
Sources: docs/blueprint/README.md and docs/ARCHITECTURE.md. Every change bumps
CONTRACTS_VERSION and is additive (ADR 0001): new fields and messages only, never changed
or removed ones.

The one exception so far is 0.4.0 (owner decision, issue #80): `CasePacket.customer_id` became
required, a tightening made before any case had been stored.

0.6.0 (ADR 0007) is additive: the login and step-up ports sit beside the B2 ones. The next version
tightens them (an account view needs a login, the step-up needs a login, `start` is for guests
only) once the lanes comply (#102, #103), the same way 0.4.0 was made.
"""

CONTRACTS_VERSION = "0.6.0"
