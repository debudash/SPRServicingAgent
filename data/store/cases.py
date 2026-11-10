"""Case store (FR-04, FR-16). The packet arrives scrubbed (FR-23); this module only persists it."""

import json
import sqlite3
from datetime import UTC, datetime

from contracts.messages import CasePacket


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
