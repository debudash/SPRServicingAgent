"""Approval tokens (GR-18, ARCHITECTURE 2.2; 0.5.0).

A token is HMAC-SHA256 of the proposal hash under `APPROVAL_SECRET`. The approval edge issues it and
the ledger re-computes it, so both sides use this one function. Because the hash covers every quote
figure, the customer, the as-of date and the contracts version, any change to the proposal after
approval voids the token.
"""

import hashlib
import hmac


def approval_token(proposal_hash: str, secret: bytes) -> str:
    if not secret:
        raise ValueError("APPROVAL_SECRET is empty: no token can be issued")
    return hmac.new(secret, proposal_hash.encode(), hashlib.sha256).hexdigest()


def tokens_match(presented: str, expected: str) -> bool:
    """Constant-time comparison, so a token cannot be guessed byte by byte."""
    return hmac.compare_digest(presented.encode(), expected.encode())
