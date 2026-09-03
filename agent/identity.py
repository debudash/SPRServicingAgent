"""Session identity + verification — the safety precondition, baked in.

Two facts live here: WHO the caller claims to be (customer_id, set when the
session starts) and WHETHER their identity is verified. Tools read both from
here; they never take a customer id or a "verified" flag from the model, so the
model cannot grant itself access or point a tool at another customer.

A session starts at the customer's on-record verification status (from
accounts.json); an unverified caller (e.g. SPR-1002) must pass verify_identity
before any account-specific action.
"""
from data import accounts

_state = {"customer_id": None, "verified": False}


def login(customer_id: str) -> None:
    acct = accounts.get_account(customer_id)
    _state["customer_id"] = customer_id
    _state["verified"] = bool(acct and acct.get("identity_verified"))


def logout() -> None:
    _state["customer_id"] = None
    _state["verified"] = False


def current_customer_id() -> str:
    if _state["customer_id"] is None:
        raise RuntimeError("No session. Call identity.login(customer_id) first.")
    return _state["customer_id"]


def is_verified() -> bool:
    return _state["verified"]


def mark_verified() -> None:
    _state["verified"] = True
