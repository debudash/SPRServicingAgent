"""Case store (FR-04, FR-16) and the reviewer's side of it (B4, FR-17: contracts 0.6.2 CaseReview).
The packet arrives scrubbed (FR-23); this module only persists it and records decisions."""

import json
import sqlite3
from datetime import UTC, datetime

from contracts.messages import (
    CASE_DECIDABLE,
    DECISION_CASE_STATUS,
    CasePacket,
    CaseReason,
    CaseStatus,
    CaseSummary,
    HumanDecision,
)


class SqliteCaseStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def open(self, packet: CasePacket) -> None:
        """Insert a new open case. A duplicate `case_id` raises sqlite3.IntegrityError."""
        reasons = {
            "rule_flags": sorted(f.value for f in packet.rule_flags),
            "compliance_reasons": [r.model_dump(mode="json") for r in packet.compliance_reasons],
        }
        # Issue #144 (found while building B4): the INSERT hard-coded NULL for proposal_id, written
        # for B2 when no case had a proposal. A withdrawal review names its proposal (0.6.1); the
        # reviewer's approval binds to it (GR-18), so the row keeps it.
        self._conn.execute(
            "INSERT INTO cases (case_id, conversation_id, customer_id, proposal_id, opened_for, "
            "reasons, packet, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                packet.case_id,
                packet.conversation_id,
                packet.customer_id,
                packet.proposal_id,
                packet.opened_for.value,
                json.dumps(reasons),
                packet.model_dump_json(),
                # Wall-clock event time, like the audit log's `at`: when the case was opened,
                # not a business date (those come from the as-of clock).
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )

    def get(self, case_id: str) -> CasePacket | None:
        row = self._conn.execute(
            "SELECT packet FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        return None if row is None else CasePacket.model_validate_json(row[0])

    # ---------- B4: CaseReview (contracts 0.6.2, #145) ----------
    def list_cases(
        self, status: CaseStatus | None = None, customer_id: str | None = None
    ) -> list[CaseSummary]:
        """Oldest first (insertion order breaks ties within a second)."""
        sql = (
            "SELECT case_id, customer_id, opened_for, status, opened_at, proposal_id, decided_by "
            "FROM cases WHERE (? IS NULL OR status = ?) AND (? IS NULL OR customer_id = ?) "
            "ORDER BY opened_at, rowid"
        )
        wanted = None if status is None else status.value
        rows = self._conn.execute(sql, (wanted, wanted, customer_id, customer_id)).fetchall()
        return [
            CaseSummary(
                case_id=r[0],
                customer_id=r[1],
                opened_for=CaseReason(r[2]),
                status=CaseStatus(r[3]),
                opened_at=datetime.fromisoformat(r[4]),
                proposal_id=r[5],
                decided_by=r[6],
            )
            for r in rows
        ]

    def status(self, case_id: str) -> CaseStatus:
        row = self._conn.execute(
            "SELECT status FROM cases WHERE case_id = ?", (case_id,)
        ).fetchone()
        if row is None:
            raise KeyError(case_id)
        return CaseStatus(row[0])

    def decide(self, decision: HumanDecision) -> None:
        """Approved and rejected are final; the check and the write are one statement, so a
        decided case is never overwritten (FR-17)."""
        current = self.status(decision.case_id)  # KeyError for an unknown case
        if current not in CASE_DECIDABLE:
            raise ValueError(f"case {decision.case_id} is already {current.value}")
        decidable = tuple(s.value for s in CASE_DECIDABLE)
        done = self._conn.execute(
            "UPDATE cases SET status = ?, decided_by = ?, decided_at = ? "
            f"WHERE case_id = ? AND status IN ({', '.join('?' * len(decidable))})",
            (
                DECISION_CASE_STATUS[decision.decision].value,
                f"human:{decision.reviewer_id}",
                datetime.now(UTC).isoformat(timespec="seconds"),
                decision.case_id,
                *decidable,
            ),
        )
        if done.rowcount != 1:  # decided by someone else between the read and the write
            raise ValueError(f"case {decision.case_id} was decided meanwhile")
