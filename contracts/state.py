"""The conversation state the graph carries, and the one node allowed to write each field
(blueprint section 4). A write by any other node is a contract violation and fails the
turn closed (FR-19).
"""

from collections.abc import Callable
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.messages import (
    AccountView,
    Approval,
    CasePacket,
    ComplianceDecision,
    Confirmation,
    Execution,
    HumanDecision,
    Intent,
    KnowledgeAnswer,
    Proposal,
    Reply,
    RuleFlags,
)
from contracts.tools import Node, Step

# PRD D-08 and D-10. Hard stops: running out ends the turn with UNAVAILABLE and no action.
MAX_FAILED_CHALLENGES = 3
MAX_HOPS_PER_TURN = 8
MAX_TOOL_CALLS_PER_TURN = 12
MAX_SECONDS_PER_TURN = 30
MAX_COST_MICROS_PER_CONVERSATION = 100_000  # $0.10


class _State(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Session(_State):
    """Who the conversation is bound to. Holds Gate A, never a date of birth or SSN digits."""

    customer_id: str | None = None
    gate_a_trusted: bool = False
    # ADR 0007 (0.6.0): the customer logged in upstream. Gate B (`gate_b_passed`) becomes the
    # step-up check before money moves.
    authenticated: bool = False
    gate_b_passed: bool = False
    failed_attempts: int = Field(default=0, ge=0, le=MAX_FAILED_CHALLENGES)
    locked: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> "Session":
        # Review follow-up on PR #20: the type allowed states no flow should produce.
        if self.failed_attempts >= MAX_FAILED_CHALLENGES and not self.locked:
            raise ValueError("the third failed challenge locks the session (D-08)")
        if self.authenticated and self.customer_id is None:
            raise ValueError("a login binds a customer")
        # Issue #108 (found by /code-review on PR #106): nothing related a pass to a lock, so a
        # passed step-up on a locked session validated. A lock only follows failed attempts made
        # before any pass, and the right answer after a lock does not unlock it (D-08, ADR 0007),
        # so no valid flow holds both.
        if self.gate_b_passed and self.locked:
            raise ValueError("a locked session cannot pass the step-up (D-08)")
        if self.gate_b_passed and (self.customer_id is None or not self.gate_a_trusted):
            raise ValueError("Gate B can only pass for a bound customer on a trusted account")
        return self


class GateResult(StrEnum):
    """What identity_gate decided this turn (ARCHITECTURE 3.2; 0.3.0). The runner clears it at
    the start of every turn, so it never carries one turn's decision into the next."""

    NO_CUSTOMER = "no_customer"  # anonymous session: account actions need a bound customer
    UNTRUSTED = "untrusted"  # Gate A fails: refuse with the contact number, never ask (GR-14)
    LOCKED = "locked"  # locked on an earlier turn (D-08)
    ASK = "ask"  # trusted, not yet verified, no usable credentials this turn: not counted
    FAILED = "failed"  # credentials did not match; attempts remain
    LOCKED_NOW = "locked_now"  # this turn's failure was the third: lock and open a case
    PASSED = "passed"  # Gate B passed this turn
    VERIFIED = "verified"  # Gate B passed on an earlier turn
    # ADR 0007 (0.6.0): logged in on a trusted account, step-up not passed. Account actions are
    # allowed; moving money still needs the step-up.
    LOGGED_IN = "logged_in"


def _challengeable(s: Session) -> bool:
    """Trusted, bound, not yet verified and not locked: the only state that may be challenged."""
    return s.customer_id is not None and s.gate_a_trusted and not s.gate_b_passed and not s.locked


# Issue #62 (found by /code-review on PR #61): only four gate results had a rule, so identity_gate
# could record a decision the session contradicts. Every value now names the session it requires,
# and a test checks the table covers the whole enum.
GATE_REQUIRES: dict[GateResult, Callable[[Session], bool]] = {
    GateResult.NO_CUSTOMER: lambda s: s.customer_id is None,
    GateResult.UNTRUSTED: lambda s: s.customer_id is not None and not s.gate_a_trusted,
    GateResult.LOCKED: lambda s: s.locked,
    GateResult.ASK: _challengeable,
    GateResult.FAILED: lambda s: _challengeable(s) and s.failed_attempts >= 1,
    GateResult.LOCKED_NOW: lambda s: s.locked,
    GateResult.PASSED: lambda s: s.gate_b_passed and not s.locked,  # issue #108
    GateResult.VERIFIED: lambda s: s.gate_b_passed and not s.locked,
    GateResult.LOGGED_IN: lambda s: (
        s.authenticated and s.gate_a_trusted and not s.locked and not s.gate_b_passed
    ),
}


class Budgets(_State):
    hops: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    turn_started_monotonic: float = 0.0
    cost_micros: int = Field(default=0, ge=0)


class Switches(_State):
    execution_enabled: bool = True  # FR-26 kill switch


class Versions(_State):
    """Copied into every audit row (FR-10, FR-27)."""

    contracts: str
    models: dict[str, str] = Field(default_factory=dict)
    prompts: dict[str, str] = Field(default_factory=dict)
    documents: dict[str, int] = Field(default_factory=dict)


class TranscriptEntry(_State):
    role: Literal["customer", "desk"]
    turn: int = Field(ge=1)
    text: str  # always scrubbed (ADR 0005)


class TraceEvent(_State):
    turn: int = Field(ge=1)
    node: Node
    step: Step | None = None


class ConversationState(_State):
    conversation_id: str
    as_of: date
    turn: int = Field(default=1, ge=1)
    session: Session = Field(default_factory=Session)
    switches: Switches = Field(default_factory=Switches)
    budgets: Budgets = Field(default_factory=Budgets)
    versions: Versions
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)

    intent: Intent | None = None
    gate: GateResult | None = None
    account_view: AccountView | None = None
    knowledge_answer: KnowledgeAnswer | None = None
    proposal: Proposal | None = None
    confirmation: Confirmation | None = None
    rule_flags: RuleFlags | None = None
    compliance: ComplianceDecision | None = None
    approval: Approval | None = None
    human_decision: HumanDecision | None = None
    execution: Execution | None = None
    case_packet: CasePacket | None = None
    reply: Reply | None = None

    @model_validator(mode="after")
    def _gates_hold(self) -> "ConversationState":
        # Issue #56: FR-02 and NG-05 as a property of the state, not only of the graph's routing.
        # An account view exists only for a trusted account (Gate A) whose customer either logged
        # in (ADR 0007) or passed the challenge (the B2 path, until the next version drops it),
        # and only for the bound customer.
        s = self.session
        if self.account_view is not None:
            if not (s.gate_a_trusted and (s.authenticated or s.gate_b_passed)):
                raise ValueError("an account view needs Gate A and a login (FR-02, ADR 0007)")
            # Issue #107 (found by /code-review on PR #106): the B2 rule needed gate_b_passed,
            # which a locked session never has, so the lock was covered implicitly. The login
            # branch has no such implication, so a locked session reached the account. The lock
            # is now named: no account view in a locked session, whichever way in (D-08, FR-04).
            if s.locked:
                raise ValueError("a locked session sees no account (D-08)")
            if self.account_view.customer_id != s.customer_id:
                raise ValueError("an account view must be the bound customer's (NG-05)")
        if self.gate is not None and not GATE_REQUIRES[self.gate](s):
            raise ValueError(f"gate {self.gate} contradicts the session (issue #62)")
        return self


def step_up_pending(state: ConversationState) -> bool:
    """ADR 0007: a step-up is pending when the customer has confirmed a withdrawal (the yes,
    GR-17) in a session that has not passed the step-up and is not locked. That confirmed
    proposal is the flow `step_up` continues. With none pending, a `step_up` call counts no
    attempt and changes nothing (review on PR #106)."""
    s = state.session
    return state.confirmation is not None and not s.gate_b_passed and not s.locked


# One writer per top-level field. `session` is created by intake and then written field by
# field: intake binds the customer and Gate A, identity_gate owns the challenge fields (see
# SESSION_FIELD_WRITERS). `transcript` and `trace` are lists only the runner appends to; an
# append does not pass through check_write, so the runner is the one place they change.
FIELD_WRITERS: dict[str, Node] = {
    "conversation_id": Node.INTAKE,
    "as_of": Node.INTAKE,
    "turn": Node.RUNNER,
    "session": Node.INTAKE,
    "switches": Node.INTAKE,
    "budgets": Node.RUNNER,
    "versions": Node.INTAKE,
    "transcript": Node.RUNNER,
    "trace": Node.RUNNER,
    "intent": Node.CONCIERGE,
    "gate": Node.IDENTITY_GATE,
    "account_view": Node.ACCOUNT,
    "knowledge_answer": Node.KNOWLEDGE,
    "proposal": Node.TRANSACTION,
    "confirmation": Node.CONFIRM,
    "rule_flags": Node.RULES,
    "compliance": Node.COMPLIANCE,
    "approval": Node.APPROVAL,
    "human_decision": Node.HUMAN_REVIEW,
    "execution": Node.EXECUTE,
    "case_packet": Node.CASE,
    "reply": Node.RESPOND,
}

SESSION_FIELD_WRITERS: dict[str, Node] = {
    "customer_id": Node.INTAKE,
    "gate_a_trusted": Node.INTAKE,
    "authenticated": Node.INTAKE,
    "gate_b_passed": Node.IDENTITY_GATE,
    "failed_attempts": Node.IDENTITY_GATE,
    "locked": Node.IDENTITY_GATE,
}


class ContractViolation(Exception):
    """A node wrote a field it does not own, or a message failed validation."""


def check_write(node: Node, field: str) -> None:
    """Raise ContractViolation unless `node` owns `field` (`session.<name>` for session fields)."""
    # Issue #23 (found by /code-review on PR #20): FIELD_WRITERS lets intake create the session,
    # and allowing it to replace the whole object would reset gate_b_passed, failed_attempts and
    # locked, which only identity_gate owns. After creation the session is written field by field.
    if field == "session":
        raise ContractViolation("write the session field by field: 'session.<field>'")
    if field.startswith("session."):
        owner = SESSION_FIELD_WRITERS.get(field.removeprefix("session."))
    else:
        owner = FIELD_WRITERS.get(field)
    if owner is None:
        raise ContractViolation(f"unknown state field {field!r}")
    if owner is not node:
        raise ContractViolation(f"{node} may not write {field!r}; only {owner} may")
