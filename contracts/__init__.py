"""Typed interfaces between lanes: handoff messages, case state, proposals, approvals, data classes.

Owned by the integrator (a human). Agent PRs that touch this folder are rejected by the pipeline.
Lanes build against these contracts, never against each other's code. The real contracts are
written after the blueprint; this stub only carries the version.
"""

CONTRACTS_VERSION = "0.0.0"
