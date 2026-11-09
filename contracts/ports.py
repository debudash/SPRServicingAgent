"""The interfaces where lanes meet (contracts 0.2.0, issue #28).

Each lane implements or calls these Protocols and never imports another lane's modules:

| Port | Implemented by | Called by |
|---|---|---|
| `KnowledgeSearch` | data (`data/knowledge_index/`) | agents (the Knowledge node) |
| `AuditLog` | data (`data/store/`) | agents (every deciding node) |
| `DeskRunner` | agents (`agents/graph.py`) | quality (`evals/run.py`), the UI |
"""

from datetime import date
from enum import StrEnum
from typing import Protocol

from pydantic import AwareDatetime, Field, JsonValue

from contracts.messages import Citation, Message
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
