"""The interfaces where lanes meet (contracts 0.2.0, issue #28; B2 ports 0.3.0, issue #56).

Each lane implements or calls these Protocols and never imports another lane's modules:

| Port | Implemented by | Called by |
|---|---|---|
| `KnowledgeSearch` | data (`data/knowledge_index/`) | agents (the Knowledge node) |
| `AuditLog` | data (`data/store/`) | agents (every deciding node) |
| `DeskRunner` | agents (`agents/graph.py`) | quality (`evals/run.py`), the UI |
| `AccountStore` | data (`data/store/`) | agents (`intake`, the account node) |
| `IdentityCheck` | data (`data/identity.py`) | agents (`identity_gate`) |
| `CaseStore` | data (`data/store/`) | agents (the case node) |
| `QuoteService` | data (`data/quote.py`) | agents (the Transaction node's `quote` tool) |
| `ProposalStore` | data (`data/store/`) | agents (Transaction, confirm, approval edge) |
| `ApprovalStore` | data (`data/store/`) | agents (the approval edge) |
| `Ledger` | data (`data/store/`) | agents (the execute node) |
| `PolicySource` | data (`data/knowledge_index/`) | agents (Compliance's `get_policy` tool) |
"""

from datetime import date
from enum import StrEnum
from typing import Protocol

from pydantic import AwareDatetime, Field, JsonValue

from contracts.messages import (
    AccountView,
    Approval,
    CasePacket,
    Citation,
    Confirmation,
    Execution,
    Message,
    Proposal,
    ProposalStatus,
    Quote,
    QuoteRefusal,
)
from contracts.outcomes import Outcome
from contracts.tools import Node, Step


# ---------- knowledge (FR-01, FR-24) ----------
class KnowledgeChunk(Message):
    """One retrievable section of a knowledge document (ARCHITECTURE.md section 2.3)."""

    doc_id: str
    version: int = Field(ge=1)
    effective_date: date
    section: str  # the `###` heading, or the FAQ question
    text: str
    source_path: str
    score: float | None = None  # similarity, when returned by a search


class KnowledgeSearch(Protocol):
    def search(self, query: str, as_of: date, k: int = 4) -> list[KnowledgeChunk]:
        """Best-matching chunks, only from document versions in force at `as_of`, best first."""
        ...


# ---------- audit (FR-10, FR-25) ----------
class AuditEvent(StrEnum):
    """Event names (ARCHITECTURE.md section 2.2). New bullets add names; none is ever removed."""

    ANSWERED = "answered"
    REFUSED = "refused"
    GATE_A_REFUSED = "gate_a_refused"
    GATE_B_PASSED = "gate_b_passed"
    GATE_B_FAILED = "gate_b_failed"
    LOCKED = "locked"
    QUOTE_SHOWN = "quote_shown"
    CONFIRMED = "confirmed"
    RULE_FLAGGED = "rule_flagged"
    COMPLIANCE_DECIDED = "compliance_decided"
    TOKEN_ISSUED = "token_issued"
    EXECUTED = "executed"
    CASE_OPENED = "case_opened"
    HUMAN_DECIDED = "human_decided"


class AuditRecord(Message):
    """One audit row as written.

    `payload` must already be scrubbed (FR-23): a precondition on the caller, checked by the
    restricted-field eval, not by this type. `versions` holds the keys of `state.Versions`:
    `contracts`, `models`, `prompts`, `documents`.
    """

    audit_id: int = Field(ge=1)
    conversation_id: str
    case_id: str | None = None
    turn: int = Field(ge=1)
    # Issue #31 (found by /code-review on PR #29): a plain str accepted any text as a time.
    # The audit trail needs an unambiguous instant; stored as ISO 8601 UTC.
    at: AwareDatetime
    node: Node
    event: AuditEvent
    payload: dict[str, JsonValue]
    versions: dict[str, JsonValue]
    prev_hash: str
    row_hash: str


class AuditLog(Protocol):
    def append(
        self,
        *,
        conversation_id: str,
        turn: int,
        node: Node,
        event: AuditEvent,
        # Issue #32 (found by /code-review on PR #29): typed like AuditRecord, so a non-JSON
        # value fails at the caller's type check instead of inside the data lane.
        payload: dict[str, JsonValue],
        versions: dict[str, JsonValue],
        case_id: str | None = None,
    ) -> AuditRecord:
        """Append one row, chained to the previous row's hash. Rows are never updated or deleted."""
        ...

    def read(self, conversation_id: str) -> list[AuditRecord]:
        """Every row for a conversation, in order (the FR-25 rebuild reads this)."""
        ...

    def verify_chain(self) -> bool:
        """True if no row has been edited, removed or reordered."""
        ...


# ---------- accounts, identity and cases (FR-02, FR-03, FR-04, PG-04) ----------
class AccountStore(Protocol):
    def gate_a(self, customer_id: str) -> bool:
        """Gate A: the account is trusted out of band (the starter kit's `identity_verified`).

        False for an unknown customer. The desk never changes it (PG-03).
        """
        ...

    def view(self, customer_id: str, as_of: date) -> AccountView:
        """The model-safe view at `as_of`: no date of birth, no SSN digits (PG-04).

        Raises KeyError for an unknown customer. Callers check both gates first; the state
        refuses a view without them (FR-02).
        """
        ...


class IdentityCheck(Protocol):
    def check_challenge(self, customer_id: str, dob: date, last4: str) -> bool:
        """Gate B: True only if both candidates match the stored values.

        Stored values never leave this call (PG-04, ADR 0005). False for an unknown customer.
        """
        ...


class CaseStore(Protocol):
    def open(self, packet: CasePacket) -> None:
        """Persist a new case. The caller picks `case_id`; a duplicate ID raises.

        The packet must already be scrubbed (FR-23): a precondition on the caller, checked by the
        restricted-field property test.
        """
        ...


# ---------- quotes, proposals, approvals and the ledger (FR-05 to FR-11; 0.5.0) ----------
class QuoteService(Protocol):
    def quote(self, customer_id: str, amount_cents: int, as_of: date) -> Quote | QuoteRefusal:
        """An exact quote from records (FR-05, D-05), with the IRS notice under 59 1/2 (FR-06) and
        the threshold tier (D-02), or a refusal with its reason (FR-07). Raises KeyError for an
        unknown customer."""
        ...


class ProposalStore(Protocol):
    def save(self, proposal: Proposal) -> None:
        """Store a new proposal with status `quoted`. A duplicate ID raises."""
        ...

    def get(self, proposal_id: str) -> Proposal | None:
        """The stored proposal (FR-08 checks it), or None."""
        ...

    def status(self, proposal_id: str) -> ProposalStatus:
        """Raises KeyError for an unknown proposal."""
        ...

    def confirm(self, confirmation: Confirmation, conversation_id: str) -> None:
        """Move `quoted` to `confirmed` (GR-17, FR-08). Raises ValueError when
        `check_confirmation` refuses the yes (another proposal, another conversation, another
        amount, or not a later turn)."""
        ...

    def move(self, proposal_id: str, status: ProposalStatus) -> None:
        """Change status. Raises ValueError when `check_transition` refuses the move."""
        ...


class ApprovalStore(Protocol):
    def record(self, approval: Approval) -> None:
        """Store a Compliance or human decision and move the proposal as `DECISION_MOVES` says
        (approve -> approved, hold or escalate -> escalated, reject -> voided, request_info ->
        unchanged), through `check_transition`, in one transaction."""
        ...


class ExecutionRefusedReason(StrEnum):
    """Why the ledger refused (FR-08 to FR-10, FR-26)."""

    UNKNOWN_PROPOSAL = "unknown_proposal"
    NOT_APPROVED = "not_approved"
    TOKEN_INVALID = "token_invalid"
    HASH_CHANGED = "hash_changed"
    EXECUTION_DISABLED = "execution_disabled"  # FR-26 kill switch


class ExecutionRefused(Exception):
    """The ledger refused to execute; nothing was written."""

    def __init__(self, reason: ExecutionRefusedReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class Ledger(Protocol):
    def execute(
        self, proposal_id: str, token: str, turn: int, versions: dict[str, JsonValue]
    ) -> Execution:
        """Execute an approved proposal (FR-08 to FR-10) in one database transaction, all of it or
        none of it. The checks run in this order (review on PR #92), each raising ExecutionRefused:

        1. Unknown proposal: UNKNOWN_PROPOSAL.
        2. Already executed: if `token` matches the one that executed it, return that first
           Execution and write nothing (FR-09 replay); otherwise TOKEN_INVALID.
        3. The deployment's execution switch is off: EXECUTION_DISABLED, whoever approved (FR-26).
        4. Status is not `approved`: NOT_APPROVED.
        5. `token` does not match `approval_token(proposal_id, stored hash, APPROVAL_SECRET)` on
           the approving row, or that row's token was already used: TOKEN_INVALID.
        6. The stored figures no longer hash to the stored hash: HASH_CHANGED.

        Then: mark the token used at `turn`, insert the transaction (proposal_id UNIQUE), move the
        proposal to `executed`, and write the `executed` audit row with the proposal's
        conversation_id and `versions`. `approved_by` comes from the approving row.
        """
        ...


class PolicySource(Protocol):
    def get_policy(self, query: str, as_of: date, k: int = 4) -> list[KnowledgeChunk]:
        """Best-matching chunks from the policy documents in force at `as_of` (Compliance only)."""
        ...


# ---------- running the desk (evals, UI) ----------
class Usage(Message):
    """Model usage for one turn, summed over every model call in it. `cost_micros` is in
    millionths of a US dollar (100_000 = $0.10), at the prices in docs/COST_MODEL.md."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    cost_micros: int = Field(default=0, ge=0)


class TurnResult(Message):
    """What one customer turn produced: everything the eval scorer reads (EVAL_SPEC section 3)."""

    conversation_id: str
    turn: int = Field(ge=1)
    reply_text: str
    outcome: Outcome
    reference: str | None = None
    citations: tuple[Citation, ...] = ()  # structured: doc_id, version, section (M-06)
    steps: tuple[Step, ...] = ()  # trace steps this turn, in order
    nodes: tuple[Node, ...] = ()  # nodes visited this turn, in order
    usage: Usage = Usage()
    latency_ms: int = Field(default=0, ge=0)
    provider_error: bool = False  # True means the eval verdict is `na`, not `fail`


class DeskRunner(Protocol):
    def start(self, customer_id: str | None) -> str:
        """Open a conversation bound to `customer_id` (None for anonymous) and return its ID.

        There is deliberately no way to start with the identity challenge already passed. An eval
        case marked `gate_b_passed: true` is set up by sending a real verification turn first,
        which the harness runs but does not score.
        """
        ...

    def send(self, conversation_id: str, text: str) -> TurnResult:
        """Run one customer turn to completion."""
        ...
