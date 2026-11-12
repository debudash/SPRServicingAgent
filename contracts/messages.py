"""Messages between nodes (docs/ARCHITECTURE.md).

Every message is validated and unknown fields are refused (FR-19), so a malformed message
fails the conversation closed instead of being interpreted.
"""

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts import CONTRACTS_VERSION
from contracts.money import surrender_charge_cents
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
    OTHER_ACCOUNT = "other_account"  # NG-05: about an account not bound to this session (0.3.0)
    RESTRICTED_INFO = "restricted_info"  # NG-08: asks the desk to disclose identity data (0.3.0)
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
    # 0.6.4 (#176): the contract's issue date, so the desk can say when it began. Not a restricted
    # field (PG-04). Optional so views built before 0.6.4 stay valid.
    contract_start_date: date | None = None


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
        # Issue #22 (found by /code-review on PR #20): the charge was never checked, so a wrong
        # charge validated. It must be the half-up surrender charge on the excess, from the one
        # shared rule in contracts.money.
        if self.charge_cents != surrender_charge_cents(self.excess_cents, self.rate_bp):
            raise ValueError("charge must be the half-up surrender charge on the excess")
        return self


def proposal_hash(customer_id: str, quote: Quote, as_of: date) -> str:
    """SHA-256 over everything an approval vouches for. Any change voids the approval (GR-18).

    It includes CONTRACTS_VERSION on purpose: an approval made under one contract version is not
    valid under another, so a contracts release voids approvals that were outstanding.
    """
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


class QuoteRefusalReason(StrEnum):
    """FR-07: why a quote was refused (0.5.0)."""

    NOT_POSITIVE = "not_positive"  # the amount is zero or less
    OVER_BALANCE = "over_balance"  # more than the current balance
    NOT_ACTIVE = "not_active"  # the account is not active


class QuoteRefusal(Message):
    """FR-07: the quote was refused; the customer is told why (NOT_PERMITTED)."""

    reason: QuoteRefusalReason


class ProposalStatus(StrEnum):
    """A proposal's life (ARCHITECTURE 2.2; 0.5.0)."""

    QUOTED = "quoted"
    CONFIRMED = "confirmed"
    APPROVED = "approved"
    EXECUTED = "executed"
    VOIDED = "voided"
    ESCALATED = "escalated"


# The only moves a proposal store may make. The yes comes before any approval (GR-17), approval
# before execution (FR-08); executed and voided are final. An escalated proposal goes to a human
# (B4), who approves or voids it.
# Issue #94 (found by /code-review on PR #92): escalation was allowed only after the yes, so a
# human-tier quote sent to a case before a valid yes (BH-B3-05) stayed confirmable, and the kill
# switch turned on after approval (FR-26) left a live token that executed once it was off. Any
# live proposal can now go to a human.
PROPOSAL_TRANSITIONS: dict[ProposalStatus, frozenset[ProposalStatus]] = {
    ProposalStatus.QUOTED: frozenset(
        {ProposalStatus.CONFIRMED, ProposalStatus.ESCALATED, ProposalStatus.VOIDED}
    ),
    ProposalStatus.CONFIRMED: frozenset(
        {ProposalStatus.APPROVED, ProposalStatus.ESCALATED, ProposalStatus.VOIDED}
    ),
    ProposalStatus.APPROVED: frozenset(
        {ProposalStatus.EXECUTED, ProposalStatus.ESCALATED, ProposalStatus.VOIDED}
    ),
    ProposalStatus.ESCALATED: frozenset({ProposalStatus.APPROVED, ProposalStatus.VOIDED}),
    ProposalStatus.EXECUTED: frozenset(),
    ProposalStatus.VOIDED: frozenset(),
}


class Confirmation(Message):
    proposal_id: str
    amount_cents: Cents = Field(gt=0)
    turn: int = Field(ge=1)


def check_transition(before: ProposalStatus, after: ProposalStatus) -> None:
    """Raise ValueError unless PROPOSAL_TRANSITIONS allows the move. Every ProposalStore calls this
    (review on PR #92: the rule must be code, not a docstring)."""
    if after not in PROPOSAL_TRANSITIONS[before]:
        raise ValueError(f"a proposal cannot move from {before} to {after}")


def check_confirmation(
    proposal: Proposal, confirmation: Confirmation, conversation_id: str
) -> None:
    """GR-17 and FR-08: a yes counts only for that proposal, in the conversation that saw the quote,
    for the quoted amount, on a later turn than the quote. Raise ValueError otherwise."""
    if confirmation.proposal_id != proposal.proposal_id:
        raise ValueError("the yes is for a different proposal")
    if conversation_id != proposal.conversation_id:
        raise ValueError("the yes came from a different conversation than the quote")
    if confirmation.amount_cents != proposal.quote.amount_cents:
        raise ValueError("the yes is for a different amount than the quote (GR-17)")
    if confirmation.turn <= proposal.quoted_turn:
        raise ValueError("the yes must come on a later turn than the quote (GR-17)")


# ---------- Rules and Compliance ----------
class RuleFlag(StrEnum):
    OVER_AMOUNT = "over_amount"  # gross over $25,000 (D-02)
    OVER_SHARE = "over_share"  # gross over 50% of balance (D-02)
    # A non-active account is refused at quote time (FR-07, QuoteRefusalReason.NOT_ACTIVE); this
    # flag only catches a status change between the quote and execution (issue #24).
    NOT_ACTIVE = "not_active"
    WAIVER_REQUEST = "waiver_request"
    FULL_SURRENDER = "full_surrender"
    AGE_80_OVER_ALLOWANCE = "age_80_over_allowance"  # D-07
    EXECUTION_DISABLED = "execution_disabled"  # FR-26
    # 0.6.1 (#136): this conversation already has a withdrawal with a person (a hold, an
    # escalation or a flag). Every later withdrawal in it goes to a person too (FR-12, GR-19).
    OPEN_REVIEW = "open_review"


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


# What each decision does to the proposal (review on PR #92). A hold is a human case (FR-12), so
# it escalates like an escalate; a human reject voids; request_info leaves it with the human.
DECISION_MOVES: dict[Decision, ProposalStatus | None] = {
    Decision.APPROVE: ProposalStatus.APPROVED,
    Decision.HOLD: ProposalStatus.ESCALATED,
    Decision.ESCALATE: ProposalStatus.ESCALATED,
    Decision.REJECT: ProposalStatus.VOIDED,
    Decision.REQUEST_INFO: None,
}

COMPLIANCE_DECISIONS = frozenset({Decision.APPROVE, Decision.HOLD, Decision.ESCALATE})
REVIEWER_DECISIONS = frozenset({Decision.APPROVE, Decision.REJECT, Decision.REQUEST_INFO})
# "compliance", or "human:<reviewer_id>" for a named reviewer.
APPROVER_PATTERN = r"^(compliance|human:[A-Za-z0-9_.-]+)$"


class Approval(Message):
    approval_id: str
    proposal_id: str
    approver: str = Field(pattern=APPROVER_PATTERN)
    decision: Decision
    token_hmac: str | None = None

    # Issue #21 (found by /code-review on PR #20): the token rule lived only in a comment, so a
    # token on a hold or escalation validated. A token is the authority to move money (GR-18):
    # it must exist exactly when the decision is APPROVE, and each approver may only make the
    # decisions its role allows.
    @model_validator(mode="after")
    def _token_only_on_approve(self) -> "Approval":
        allowed = COMPLIANCE_DECISIONS if self.approver == "compliance" else REVIEWER_DECISIONS
        if self.decision not in allowed:
            raise ValueError(f"{self.approver} cannot decide {self.decision}")
        if (self.decision is Decision.APPROVE) != (self.token_hmac is not None):
            raise ValueError("a token is issued exactly when the decision is approve")
        return self


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
    approved_by: str = Field(pattern=APPROVER_PATTERN)  # issue #21


# ---------- Cases and replies ----------
class CaseReason(StrEnum):
    """Why a case was opened (0.3.0). New bullets add reasons; none is ever removed."""

    LOCKED = "locked"  # third failed identity challenge (D-08, FR-04)
    THIRD_PARTY = "third_party"  # someone acting for the customer (D-09)
    # 0.6.1 (#89): a proposal exists and a person must review it. The rules flagged it (D-02,
    # D-07, FR-26), Compliance held or escalated it (FR-11, FR-12), or the customer asked to go
    # ahead with a human-tier quote (GR-19). The packet names the proposal and carries its quote.
    # Requests with no proposal (a waiver asked before any amount, RMD, hardship) get their own
    # reasons when they are built.
    WITHDRAWAL_REVIEW = "withdrawal_review"
    # 0.6.2 (B4): requests only a person may decide, with no proposal of their own.
    WAIVER_REQUEST = "waiver_request"  # FR-13, NG-01: a waiver is always a human's decision (D-03)
    HARDSHIP = "hardship"  # FR-14: no general hardship waiver; a servicing case on request
    RMD = "rmd"  # FR-15, PG-07: explained from the documents, then escalated
    FULL_SURRENDER = "full_surrender"  # NG-07: a full surrender always goes to a person


class CaseStatus(StrEnum):
    """0.6.2 (B4): where a case stands. The store's `cases.status` column holds these values."""

    OPEN = "open"
    INFO_REQUESTED = "info_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    CLOSED = "closed"


# 0.6.2: a reviewer decides an open case, or one waiting on information (FR-17). What the decision
# makes of it; approved and rejected are final.
CASE_DECIDABLE = frozenset({CaseStatus.OPEN, CaseStatus.INFO_REQUESTED})
DECISION_CASE_STATUS: dict[Decision, CaseStatus] = {
    Decision.APPROVE: CaseStatus.APPROVED,
    Decision.REJECT: CaseStatus.REJECTED,
    Decision.REQUEST_INFO: CaseStatus.INFO_REQUESTED,
}


class CasePacket(Message):
    """FR-16. No field is a restricted field (tested). The free-text fields (`request_summary`,
    `excerpt`) rely on the scrubber (FR-23, ADR 0005) before the packet is built."""

    case_id: str
    conversation_id: str
    # Issue #80 (owner decision): every case names its customer. A third party who does not
    # identify an account gets no case (D-09 applies to an account bound to the session).
    customer_id: str = Field(min_length=1)
    opened_for: CaseReason
    request_summary: str
    quote: Quote | None
    rule_flags: frozenset[RuleFlag] = frozenset()
    compliance_reasons: tuple[Reason, ...] = ()
    excerpt: str
    recommendation: str
    # 0.6.1 (#89, review on PR #134): the proposal under review, so a reviewer's approval binds to
    # it (GR-18, ARCHITECTURE 3.4), and what Compliance decided, so hold and escalate stay
    # distinguishable and the vulnerable-customer signals reach the reviewer (FR-11, FR-12).
    proposal_id: str | None = None
    compliance_decision: Decision | None = None
    signals: frozenset[Signal] = frozenset()

    @model_validator(mode="after")
    def _review_names_its_proposal(self) -> "CasePacket":
        # 0.6.1: a reviewer decides on the proposal and the figures the customer saw, so a
        # withdrawal review without them cannot be acted on.
        if self.opened_for is CaseReason.WITHDRAWAL_REVIEW and (
            self.quote is None or self.proposal_id is None
        ):
            raise ValueError("a withdrawal review names its proposal and carries its quote")
        return self


class CaseSummary(Message):
    """0.6.2: one row of the review queue (FR-17). The packet itself comes from `CaseStore.get`."""

    case_id: str
    customer_id: str
    opened_for: CaseReason
    status: CaseStatus
    opened_at: datetime
    proposal_id: str | None = None
    decided_by: str | None = None  # "human:<reviewer_id>" once decided


class ReviewResult(Message):
    """0.6.2: what a reviewer's decision did (FR-17, FR-18). `reference` is the transaction ID when
    the approval executed a withdrawal, else the case ID."""

    case_id: str
    decision: Decision
    outcome: Outcome
    reference: str
    text: str

    @model_validator(mode="after")
    def _only_an_approval_executes(self) -> "ReviewResult":
        if self.outcome is Outcome.EXECUTED and self.decision is not Decision.APPROVE:
            raise ValueError("only an approval executes a withdrawal (FR-17)")
        return self


class Reply(Message):
    text: str
    outcome: Outcome
    reference: str | None = None  # transaction ID or case ID shown to the customer
