"""Data classification per desk.db column (docs/ARCHITECTURE.md section 2.2)."""

from enum import StrEnum


class Classification(StrEnum):
    PUBLIC = "P"
    INTERNAL = "I"
    CONFIDENTIAL = "C"
    RESTRICTED = "R"


PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED = (
    Classification.PUBLIC,
    Classification.INTERNAL,
    Classification.CONFIDENTIAL,
    Classification.RESTRICTED,
)

COLUMNS: dict[str, dict[str, Classification]] = {
    "accounts": {
        "customer_id": INTERNAL,
        "name": CONFIDENTIAL,
        "email": CONFIDENTIAL,
        "phone": CONFIDENTIAL,
        "account_status": INTERNAL,
        "gate_a_trusted": INTERNAL,
        "balance_cents": CONFIDENTIAL,
        "initial_deposit_cents": CONFIDENTIAL,
        "contract_start_date": INTERNAL,
        "contract_year_stored": INTERNAL,
        "is_synthetic": INTERNAL,
    },
    "identity": {"customer_id": INTERNAL, "dob": RESTRICTED, "ssn_last4": RESTRICTED},
    "beneficiaries": {
        "beneficiary_id": INTERNAL,
        "customer_id": INTERNAL,
        "name": CONFIDENTIAL,
        "relationship": CONFIDENTIAL,
        "percentage": INTERNAL,
    },
    "transactions": {
        "transaction_id": INTERNAL,
        "customer_id": INTERNAL,
        "proposal_id": INTERNAL,
        "contract_year": INTERNAL,
        "gross_cents": CONFIDENTIAL,
        "free_cents": CONFIDENTIAL,
        "excess_cents": CONFIDENTIAL,
        "charge_cents": CONFIDENTIAL,
        "net_cents": CONFIDENTIAL,
        "approved_by": INTERNAL,
        "executed_as_of": INTERNAL,
        "is_synthetic": INTERNAL,
    },
    "conversations": {
        "conversation_id": INTERNAL,
        "customer_id": INTERNAL,
        "started_at": INTERNAL,
        "as_of": INTERNAL,
        "gate_b_passed": INTERNAL,
        "failed_attempts": INTERNAL,
        "locked": INTERNAL,
        "cost_usd_micros": INTERNAL,
    },
    "proposals": {
        "proposal_id": INTERNAL,
        "conversation_id": INTERNAL,
        "customer_id": INTERNAL,
        "amount_cents": CONFIDENTIAL,
        "free_cents": CONFIDENTIAL,
        "excess_cents": CONFIDENTIAL,
        "charge_cents": CONFIDENTIAL,
        "net_cents": CONFIDENTIAL,
        "rate_bp": PUBLIC,
        "threshold_tier": INTERNAL,
        "hash": INTERNAL,
        "status": INTERNAL,
        "quoted_turn": INTERNAL,
        "confirmed_turn": INTERNAL,
    },
    "approvals": {
        "approval_id": INTERNAL,
        "proposal_id": INTERNAL,
        "approver": INTERNAL,
        "decision": INTERNAL,
        "reasons": INTERNAL,
        "token_hmac": INTERNAL,
        "used_at_turn": INTERNAL,
    },
    "cases": {
        "case_id": INTERNAL,
        "conversation_id": INTERNAL,
        "customer_id": INTERNAL,
        "proposal_id": INTERNAL,
        "reasons": INTERNAL,
        "packet": CONFIDENTIAL,
        "status": INTERNAL,
        "decided_by": INTERNAL,
        "decided_at": INTERNAL,
    },
    "audit": {
        "audit_id": INTERNAL,
        "conversation_id": INTERNAL,
        "case_id": INTERNAL,
        "turn": INTERNAL,
        "at": INTERNAL,
        "node": INTERNAL,
        "event": INTERNAL,
        "payload": CONFIDENTIAL,
        "versions": INTERNAL,
        "prev_hash": INTERNAL,
        "row_hash": INTERNAL,
    },
}

RESTRICTED_FIELDS = frozenset(
    column for table in COLUMNS.values() for column, cls in table.items() if cls is RESTRICTED
)
