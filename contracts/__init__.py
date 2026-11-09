"""Typed interfaces between lanes: outcomes, roles and tools, money, classification,
messages and state.

Owned by the integrator (a human). Agent PRs that touch this folder are rejected by the
pipeline. Lanes build against these contracts, never against each other's code.
Sources: docs/blueprint/README.md and docs/ARCHITECTURE.md. Every change bumps
CONTRACTS_VERSION and is additive (ADR 0001): new fields and messages only, never changed
or removed ones.
"""

CONTRACTS_VERSION = "0.2.0"
