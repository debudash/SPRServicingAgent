"""Data classification per desk.db column (docs/ARCHITECTURE.md section 2.2)."""

from enum import StrEnum


class Classification(StrEnum):
    PUBLIC = "P"
    INTERNAL = "I"
    CONFIDENTIAL = "C"
    RESTRICTED = "R"


PUB, INT, CONF, RESTR = (
    Classification.PUBLIC,
    Classification.INTERNAL,
    Classification.CONFIDENTIAL,
    Classification.RESTRICTED,
)

COLUMNS: dict[str, dict[str, Classification]] = {
    "accounts": {
        "customer_id": INT,
        "name": CONF,
        "email": CONF,
        "phone": CONF,
        "account_status": INT,
        "gate_a_trusted": INT,
        "balance_cents": CONF,
        "initial_deposit_cents": CONF,
        "contract_start_date": INT,
        "contract_year_stored": INT,
        "is_synthetic": INT,
    },
    "identity": {"customer_id": INT, "dob": RESTR, "ssn_last4": RESTR},
    "beneficiaries": {
        "beneficiary_id": INT,
        "customer_id": INT,
        "name": CONF,
        "relationship": CONF,
        "percentage": INT,
    },
    "transactions": {
        "transaction_id": INT,
        "customer_id": INT,
        "proposal_id": INT,
        "contract_year": INT,
        "gross_cents": CONF,
        "free_cents": CONF,
        "excess_cents": CONF,
        "charge_cents": CONF,
        "net_cents": CONF,
        "approved_by": INT,
        "executed_as_of": INT,
        "is_synthetic": INT,
    },
    "conversations": {
        "conversation_id": INT,
        "customer_id": INT,
        "started_at": INT,
        "as_of": INT,
        "gate_b_passed": INT,
        "failed_attempts": INT,
        "locked": INT,
        "cost_usd_micros": INT,
    },
    "proposals": {
        "proposal_id": INT,
        "conversation_id": INT,
        "customer_id": INT,
        "amount_cents": CONF,
        "free_cents": CONF,
        "excess_cents": CONF,
        "charge_cents": CONF,
        "net_cents": CONF,
        "rate_bp": PUB,
        "threshold_tier": INT,
        "hash": INT,
        "status": INT,
        "quoted_turn": INT,
        "confirmed_turn": INT,
    },
    "approvals": {
        "approval_id": INT,
        "proposal_id": INT,
        "approver": INT,
        "decision": INT,
        "reasons": INT,
        "token_hmac": INT,
        "used_at_turn": INT,
    },
    "cases": {
        "case_id": INT,
        "conversation_id": INT,
        "customer_id": INT,
        "proposal_id": INT,
        "reasons": INT,
        "packet": CONF,
        "status": INT,
        "decided_by": INT,
        "decided_at": INT,
    },
    "audit": {
        "audit_id": INT,
        "conversation_id": INT,
        "case_id": INT,
        "turn": INT,
        "at": INT,
        "node": INT,
        "event": INT,
        "payload": CONF,
        "versions": INT,
        "prev_hash": INT,
        "row_hash": INT,
    },
}

RESTRICTED_FIELDS = frozenset(
    column for table in COLUMNS.values() for column, cls in table.items() if cls is RESTR
)
