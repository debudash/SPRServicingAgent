"""Approval tokens (GR-18, ARCHITECTURE 2.2; 0.5.0).

A token is HMAC-SHA256 of the proposal ID and hash under `APPROVAL_SECRET`. The approval edge issues
it and the ledger re-computes it, so both sides use this one function. Because the hash covers every
quote figure, the customer, the as-of date and the contracts version, any change to the proposal
after approval voids the token.
"""

import hashlib
import hmac

_SEPARATOR = "\x00"  # cannot occur in a proposal ID, so the two parts cannot run together


def approval_token(proposal_id: str, proposal_hash: str, secret: bytes) -> str:
    # Issue #93 (found by /code-review on PR #92): the token covered only the hash, so two
    # proposals with identical figures on the same as-of date shared a token, and a ledger could
    # consume or record the wrong approval. The ID binds it to that one proposal (GR-18).
    if not secret:
        raise ValueError("APPROVAL_SECRET is empty: no token can be issued")
    if not proposal_id or _SEPARATOR in proposal_id:
        raise ValueError("a token needs a proposal ID")
    message = f"{proposal_id}{_SEPARATOR}{proposal_hash}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def tokens_match(presented: str, expected: str) -> bool:
    """Constant-time comparison, so a token cannot be guessed byte by byte."""
    return hmac.compare_digest(presented.encode(), expected.encode())
