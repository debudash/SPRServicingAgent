"""Messages between nodes (docs/ARCHITECTURE.md).

Every message is validated and unknown fields are refused (FR-19), so a malformed message
fails the conversation closed instead of being interpreted.
"""

import hashlib
import json
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts import CONTRACTS_VERSION
from contracts.outcomes import Outcome

Cents = int  # integer cents; see contracts.money


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------- Concierge ----------
class IntentKind(StrEnum):
    PRODUCT_QUESTION = "product_question"
    ACCOUNT_INFO = "account_info"
    WITHDRAWAL = "withdrawal"
    CONFIRM = "confirm"
    FULL_SURRENDER = "full_surrender"
    HARDSHIP_WAIVER = "hardship_waiver"
    RMD = "rmd"
    THIRD_PARTY = "third_party"
    CHANGE_DETAILS = "change_details"
    VERIFY = "verify"
    OUT_OF_SCOPE = "out_of_scope"
    OTHER = "other"


class Intent(Message):
    kind: IntentKind
    amount_cents: Cents | None = Field(default=None, ge=0)
    explicit_yes: bool = False  # GR-17: an unambiguous yes; `confirm` still checks amount and order


# ---------- Knowledge ----------
class Citation(Message):
    doc_id: str
    version: int = Field(ge=1)
    section: str


class KnowledgeAnswer(Message):
    found: bool  # False means NO_SOURCE (GR-05)
    text: str
    citations: tuple[Citation, ...] = ()

    @model_validator(mode="after")
    def _found_answers_cite(self) -> "KnowledgeAnswer":
        if self.found and not self.citations:
            raise ValueError("an answer from the knowledge base must cite it (GR-01)")
        return self


# ---------- Account ----------
class AgeBand(StrEnum):
    UNDER_59_5 = "under_59_5"
    FROM_59_5_TO_79 = "59_5_to_79"
    EIGHTY_PLUS = "80_plus"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    FROZEN = "frozen"
    DECEASED = "deceased"


class AccountView(Message):
    """What a model may see of an account: no date of birth, no SSN digits (PG-04)."""

    customer_id: str
    account_status: AccountStatus
    contract_year: int = Field(ge=1)
    age_band: AgeBand
    balance_cents: Cents = Field(ge=0)
    allowance_remaining_cents: Cents = Field(ge=0)
    withdrawals_this_year: int = Field(ge=0)


# ---------- Quote and proposal ----------
class ThresholdTier(StrEnum):
    SELF_SERVICE = "self_service"
    HUMAN = "human"


class Quote(Message):
    amount_cents: Cents = Field(gt=0)
    free_cents: Cents = Field(ge=0)
    excess_cents: Cents = Field(ge=0)
    rate_bp: int = Field(ge=0, le=10_000)
    charge_cents: Cents = Field(ge=0)
    net_cents: Cents = Field(ge=0)
    contract_year: int = Field(ge=1)
    threshold_tier: ThresholdTier
    irs_notice: bool

    @model_validator(mode="after")
    def _figures_add_up(self) -> "Quote":
        if self.net_cents != self.amount_cents - self.charge_cents:
            raise ValueError("net must equal amount minus charge")
        if self.excess_cents != max(0, self.amount_cents - self.free_cents):
            raise ValueError("excess must equal amount minus free allowance, floored at 0")
        return self


def proposal_hash(customer_id: str, quote: Quote, as_of: date) -> str:
    """SHA-256 over everything an approval vouches for. Any change voids the approval (GR-18)."""
    body = {
        "contracts_version": CONTRACTS_VERSION,
        "customer_id": customer_id,
        "as_of": as_of.isoformat(),
        "quote": quote.model_dump(mode="json"),
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class Proposal(Message):
    proposal_id: str
    conversation_id: str
    customer_id: str
    quote: Quote
    as_of: date
    quoted_turn: int = Field(ge=1)
    hash: str

    @model_validator(mode="after")
    def _hash_matches(self) -> "Proposal":
        if self.hash != proposal_hash(self.customer_id, self.quote, self.as_of):
            raise ValueError("proposal hash does not match its contents")
        return self


class Confirmation(Message):
    proposal_id: str
    amount_cents: Cents = Field(gt=0)
    turn: int = Field(ge=1)


# ---------- Rules and Compliance ----------
class RuleFlag(StrEnum):
    OVER_AMOUNT = "over_amount"  # gross over $25,000 (D-02)
    OVER_SHARE = "over_share"  # gross over 50% of balance (D-02)
    NOT_ACTIVE = "not_active"
    WAIVER_REQUEST = "waiver_request"
    FULL_SURRENDER = "full_surrender"
    AGE_80_OVER_ALLOWANCE = "age_80_over_allowance"  # D-07
    EXECUTION_DISABLED = "execution_disabled"  # FR-26


class RuleFlags(Message):
    proposal_id: str
    flags: frozenset[RuleFlag] = frozenset()


class Decision(StrEnum):
    APPROVE = "approve"
    HOLD = "hold"
    ESCALATE = "escalate"
    REJECT = "reject"  # human reviewers only
    REQUEST_INFO = "request_info"  # human reviewers only


class Signal(StrEnum):
    """Conversational vulnerable-customer signals judged by Compliance (D-07)."""

    THIRD_PARTY = "third_party"
    PRESSURE = "pressure"
    CONFUSION = "confusion"


class Reason(Message):
    policy_ref: str  # "doc_id vN §section"
    text: str


class ComplianceDecision(Message):
    proposal_id: str
    decision: Decision
    reasons: tuple[Reason, ...] = Field(min_length=1)
    signals: frozenset[Signal] = frozenset()

    @model_validator(mode="after")
    def _agent_decisions_only(self) -> "ComplianceDecision":
        if self.decision not in {Decision.APPROVE, Decision.HOLD, Decision.ESCALATE}:
            raise ValueError("Compliance decides approve, hold or escalate; reject is for humans")
        if self.decision is Decision.APPROVE and self.signals:
            raise ValueError("a vulnerable-customer signal cannot be approved (FR-12)")
        return self


class Approval(Message):
    approval_id: str
    proposal_id: str
    approver: str  # "compliance" or "human:<reviewer_id>"
    decision: Decision
    token_hmac: str | None = None  # present only on an approval to execute


class HumanDecision(Message):
    case_id: str
    reviewer_id: str
    decision: Decision
    note: str = ""

    @model_validator(mode="after")
    def _human_decisions_only(self) -> "HumanDecision":
        if self.decision not in {Decision.APPROVE, Decision.REJECT, Decision.REQUEST_INFO}:
            raise ValueError("reviewers approve, reject or request information")
        return self


class Execution(Message):
    transaction_id: str
    proposal_id: str
    approved_by: str


# ---------- Cases and replies ----------
class CasePacket(Message):
    """FR-16. Scrubbed before it is written; never holds restricted fields."""

    case_id: str
    conversation_id: str
    customer_id: str | None
    request_summary: str
    quote: Quote | None
    rule_flags: frozenset[RuleFlag] = frozenset()
    compliance_reasons: tuple[Reason, ...] = ()
    excerpt: str
    recommendation: str


class Reply(Message):
    text: str
    outcome: Outcome
    reference: str | None = None  # transaction ID or case ID shown to the customer
