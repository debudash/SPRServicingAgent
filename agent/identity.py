"""Session identity — two gates in series, neither of them settable by the model.

GATE A — ACCOUNT TRUST (accounts.json `identity_verified`)
    SPR established this customer's identity out of band (KYC/servicing records).
    It says the RECORD can be trusted for financial transactions. It is static:
    nothing said in a chat can earn it. If it is false, the agent stops — the
    customer must verify with SPR through the proper channel first.

GATE B — SESSION CHALLENGE (verify_identity: date of birth + last 4 of SSN)
    Proves the CALLER is that customer, for this session. Starts false every
    session, for everyone, and only counts on an account that already passed
    Gate A. Passing it on an untrusted account is meaningless and refused.

Account-specific tools require BOTH. The customer_id comes from the session, never
from the model, so no tool can be pointed at another customer.

Also tracks which withdrawal amounts have actually been quoted (via
calculate_withdrawal) this session — execute_withdrawal is code-gated on this, so
the model can't skip straight to moving money without showing the charges.
"""
from data import accounts

_state = {"customer_id": None, "session_verified": False, "quoted_amounts": set()}


def login(customer_id: str) -> None:
    """Start a session. The session challenge (Gate B) always starts unpassed —
    account trust (Gate A) is read live from the record and never mutated here."""
    _state["customer_id"] = customer_id
    _state["session_verified"] = False
    _state["quoted_amounts"] = set()


def logout() -> None:
    _state["customer_id"] = None
    _state["session_verified"] = False
    _state["quoted_amounts"] = set()


def current_customer_id() -> str:
    if _state["customer_id"] is None:
        raise RuntimeError("No session. Call identity.login(customer_id) first.")
    return _state["customer_id"]


def account_is_trusted() -> bool:
    """Gate A: has SPR verified this customer on record? Read-only, out of band."""
    acct = accounts.get_account(_state["customer_id"]) if _state["customer_id"] else None
    return bool(acct and acct.get("identity_verified"))


def challenge_passed() -> bool:
    """Gate B: has the caller proven who they are this session?"""
    return _state["session_verified"]


def is_verified() -> bool:
    """Both gates. What every account-specific tool checks."""
    return account_is_trusted() and challenge_passed()


def mark_verified() -> None:
    """Only ever called after a passed challenge on a trusted account."""
    _state["session_verified"] = True


def record_quote(amount: float) -> None:
    _state["quoted_amounts"].add(round(float(amount), 2))


def is_quoted(amount: float) -> bool:
    return round(float(amount), 2) in _state["quoted_amounts"]
