"""Proposal and approval stores (GR-17, FR-08, ARCHITECTURE 2.2).

Every status change reads the current status and writes the new one inside one `BEGIN IMMEDIATE`,
so two writers cannot both move the same proposal. The rules themselves come from the contracts
(`check_confirmation`, `check_transition`, `DECISION_MOVES`); this module only applies them.
"""

import sqlite3
from datetime import UTC, date, datetime
from typing import Any

from contracts.messages import (
    DECISION_MOVES,
    Approval,
    Confirmation,
    Decision,
    Proposal,
    ProposalStatus,
    Quote,
    ThresholdTier,
    check_confirmation,
    check_transition,
)
from data.store.db import immediate

PROPOSAL_COLUMNS = (
    "proposal_id, conversation_id, customer_id, amount_cents, free_cents, excess_cents, rate_bp, "
    "charge_cents, net_cents, contract_year, threshold_tier, irs_notice, as_of, hash, quoted_turn"
)


_MOVE_TARGETS = frozenset({ProposalStatus.ESCALATED, ProposalStatus.VOIDED})


def _now() -> str:
    # Wall-clock event time, like the audit log's `at`; business dates come from the as-of clock.
    return datetime.now(UTC).isoformat(timespec="seconds")


def proposal_from_row(row: tuple[Any, ...]) -> Proposal:
    """Rebuild a Proposal from `PROPOSAL_COLUMNS`. Raises ValueError (pydantic ValidationError)
    if the stored figures no longer add up or no longer match the stored hash."""
    quote = Quote(
        amount_cents=row[3],
        free_cents=row[4],
        excess_cents=row[5],
        rate_bp=row[6],
        charge_cents=row[7],
        net_cents=row[8],
        contract_year=row[9],
        threshold_tier=ThresholdTier(str(row[10])),
        irs_notice=bool(row[11]),
    )
    return Proposal(
        proposal_id=str(row[0]),
        conversation_id=str(row[1]),
        customer_id=str(row[2]),
        quote=quote,
        as_of=date.fromisoformat(str(row[12])),
        hash=str(row[13]),
        quoted_turn=int(row[14]),
    )


def read_status(conn: sqlite3.Connection, proposal_id: str) -> ProposalStatus:
    row = conn.execute(
        "SELECT status FROM proposals WHERE proposal_id = ?", (proposal_id,)
    ).fetchone()
    if row is None:
        raise KeyError(proposal_id)
    return ProposalStatus(row[0])


def write_status(
    conn: sqlite3.Connection, proposal_id: str, before: ProposalStatus, after: ProposalStatus
) -> None:
    """The one status write. Call inside a transaction, after reading `before` in it."""
    check_transition(before, after)
    conn.execute(
        "UPDATE proposals SET status = ? WHERE proposal_id = ? AND status = ?",
        (after.value, proposal_id, before.value),
    )


class SqliteProposalStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, proposal: Proposal) -> None:
        """Insert with status `quoted`. A duplicate ID raises sqlite3.IntegrityError."""
        q = proposal.quote
        self._conn.execute(
            f"INSERT INTO proposals ({PROPOSAL_COLUMNS}, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'quoted', ?)",
            (
                proposal.proposal_id,
                proposal.conversation_id,
                proposal.customer_id,
                q.amount_cents,
                q.free_cents,
                q.excess_cents,
                q.rate_bp,
                q.charge_cents,
                q.net_cents,
                q.contract_year,
                q.threshold_tier.value,
                int(q.irs_notice),
                proposal.as_of.isoformat(),
                proposal.hash,
                proposal.quoted_turn,
                _now(),
            ),
        )

    def get(self, proposal_id: str) -> Proposal | None:
        row = self._conn.execute(
            f"SELECT {PROPOSAL_COLUMNS} FROM proposals WHERE proposal_id = ?", (proposal_id,)
        ).fetchone()
        return None if row is None else proposal_from_row(row)

    def status(self, proposal_id: str) -> ProposalStatus:
        return read_status(self._conn, proposal_id)

    def confirm(self, confirmation: Confirmation, conversation_id: str) -> None:
        with immediate(self._conn):
            proposal = self.get(confirmation.proposal_id)
            if proposal is None:
                raise KeyError(confirmation.proposal_id)
            check_confirmation(proposal, confirmation, conversation_id)  # GR-17
            before = read_status(self._conn, proposal.proposal_id)
            write_status(self._conn, proposal.proposal_id, before, ProposalStatus.CONFIRMED)
            self._conn.execute(
                "UPDATE proposals SET confirmed_turn = ? WHERE proposal_id = ?",
                (confirmation.turn, proposal.proposal_id),
            )

    def move(self, proposal_id: str, status: ProposalStatus) -> None:
        # Issue #99 (found by /code-review on PR #96): move accepted every target the transition
        # table allows, so it could mark a proposal confirmed, approved or executed without the
        # yes, the approval row or the ledger. Those three have their own paths (confirm,
        # ApprovalStore.record, Ledger.execute) carrying the checks; move only sends a proposal to
        # a human or voids it.
        if status not in _MOVE_TARGETS:
            raise ValueError(f"move cannot set {status}; it has its own path")
        with immediate(self._conn):
            write_status(self._conn, proposal_id, read_status(self._conn, proposal_id), status)


class SqliteApprovalStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, approval: Approval) -> None:
        """Store the decision and apply `DECISION_MOVES` in one transaction, or neither.

        Beyond the transition table, two role rules (FR-08, D-02, ARCHITECTURE 3.3/3.4):
        Compliance decides only a confirmed proposal, never one already with a human; and it may
        approve only the self-service tier. Humans decide only an escalated proposal, so a
        reviewer never stands in for Compliance. Each refusal raises ValueError and writes nothing.
        """
        with immediate(self._conn):
            pid = approval.proposal_id
            before = read_status(self._conn, pid)  # KeyError for an unknown proposal
            if approval.approver == "compliance":
                if before is not ProposalStatus.CONFIRMED:
                    raise ValueError(f"Compliance decides confirmed proposals, not {before}")
                tier = self._conn.execute(
                    "SELECT threshold_tier FROM proposals WHERE proposal_id = ?", (pid,)
                ).fetchone()[0]
                if approval.decision is Decision.APPROVE and tier != ThresholdTier.SELF_SERVICE:
                    raise ValueError("Compliance cannot approve a human-tier proposal (D-02)")
            elif before is not ProposalStatus.ESCALATED:
                raise ValueError(f"a reviewer decides escalated proposals, not {before}")
            after = DECISION_MOVES[approval.decision]
            if after is not None:
                write_status(self._conn, pid, before, after)
            self._conn.execute(
                "INSERT INTO approvals (approval_id, proposal_id, approver, decision, token_hmac, "
                "recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    approval.approval_id,
                    pid,
                    approval.approver,
                    approval.decision.value,
                    approval.token_hmac,
                    _now(),
                ),
            )
