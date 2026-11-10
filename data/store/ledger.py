"""The ledger: the only writer of `transactions` (FR-08 to FR-10, FR-26, GR-18).

`execute` runs the checks in the order `contracts.ports.Ledger` fixes, then writes the token use,
the transaction, the status and the `executed` audit row, all inside one `BEGIN IMMEDIATE`. Any
refusal or error rolls every write back, so the audit row and the money move together or not at all.
"""

import sqlite3
from uuid import uuid4

from pydantic import JsonValue, ValidationError

from contracts.messages import Execution, ProposalStatus, proposal_hash
from contracts.ports import AuditEvent, ExecutionRefused, ExecutionRefusedReason
from contracts.tokens import approval_token, tokens_match
from contracts.tools import Node
from data.store.audit import SqliteAuditLog
from data.store.db import immediate
from data.store.proposals import PROPOSAL_COLUMNS, proposal_from_row, write_status


class SqliteLedger:
    def __init__(
        self,
        conn: sqlite3.Connection,
        audit: SqliteAuditLog,
        *,
        secret: bytes,
        execution_enabled: bool,
    ) -> None:
        self._conn = conn
        self._audit = audit
        self._secret = secret
        self._enabled = execution_enabled

    def execute(
        self, proposal_id: str, token: str, turn: int, versions: dict[str, JsonValue]
    ) -> Execution:
        with immediate(self._conn):
            return self._execute(proposal_id, token, turn, versions)

    def _execute(
        self, proposal_id: str, token: str, turn: int, versions: dict[str, JsonValue]
    ) -> Execution:
        c = self._conn
        row = c.execute(
            f"SELECT {PROPOSAL_COLUMNS}, status FROM proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        # 1. Unknown proposal.
        if row is None:
            raise ExecutionRefused(ExecutionRefusedReason.UNKNOWN_PROPOSAL)
        status = ProposalStatus(row[-1])
        stored_hash = str(row[13])

        # 2. Already executed: the token that executed it gets the first Execution back (FR-09).
        if status is ProposalStatus.EXECUTED:
            return self._replay(proposal_id, token)

        # 3. FR-26: the switch is off, whoever approved.
        if not self._enabled:
            raise ExecutionRefused(ExecutionRefusedReason.EXECUTION_DISABLED)

        # 4. Only an approved proposal executes (FR-08).
        if status is not ProposalStatus.APPROVED:
            raise ExecutionRefused(ExecutionRefusedReason.NOT_APPROVED)

        # 5. The token on the latest approving row: re-computed here, never trusted from the row,
        #    and single use (GR-18). Raises ValueError for an empty secret (nothing is written).
        expected = approval_token(proposal_id, stored_hash, self._secret)
        approving = c.execute(
            "SELECT approval_id, approver, token_hmac, used_at_turn FROM approvals "
            "WHERE proposal_id = ? AND decision = 'approve' ORDER BY rowid DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        if (
            approving is None
            or approving[3] is not None
            or not tokens_match(str(approving[2]), expected)
            or not tokens_match(token, expected)
        ):
            raise ExecutionRefused(ExecutionRefusedReason.TOKEN_INVALID)
        approval_id, approved_by = str(approving[0]), str(approving[1])

        # 6. The stored figures must still hash to the hash that was approved. Figures that no
        #    longer add up fail the Quote contract: that is a changed proposal too.
        try:
            proposal = proposal_from_row(row[:-1])
        except ValidationError:
            raise ExecutionRefused(ExecutionRefusedReason.HASH_CHANGED) from None
        recomputed = proposal_hash(proposal.customer_id, proposal.quote, proposal.as_of)
        if recomputed != stored_hash:  # proposal_from_row checks this too; kept explicit
            raise ExecutionRefused(ExecutionRefusedReason.HASH_CHANGED)

        q = proposal.quote
        transaction_id = f"TX-{uuid4().hex[:12].upper()}"
        c.execute(
            "UPDATE approvals SET used_at_turn = ? WHERE approval_id = ?", (turn, approval_id)
        )
        c.execute(
            "INSERT INTO transactions (transaction_id, customer_id, proposal_id, contract_year, "
            "gross_cents, free_cents, excess_cents, charge_cents, net_cents, approved_by, "
            "executed_as_of, is_synthetic) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                transaction_id,
                proposal.customer_id,
                proposal_id,
                q.contract_year,
                q.amount_cents,
                # The free part this withdrawal used, as the seeded history records it; the
                # quote's free_cents is the whole remaining allowance, which may be larger.
                q.amount_cents - q.excess_cents,
                q.excess_cents,
                q.charge_cents,
                q.net_cents,
                approved_by,
                proposal.as_of.isoformat(),  # the business date the approval vouched for
            ),
        )
        write_status(c, proposal_id, status, ProposalStatus.EXECUTED)
        self._audit.append_in_transaction(
            conversation_id=proposal.conversation_id,
            turn=turn,
            node=Node.EXECUTE,
            event=AuditEvent.EXECUTED,
            payload={
                "proposal_id": proposal_id,
                "transaction_id": transaction_id,
                "approved_by": approved_by,
            },
            versions=versions,
        )
        return Execution(
            transaction_id=transaction_id, proposal_id=proposal_id, approved_by=approved_by
        )

    def _replay(self, proposal_id: str, token: str) -> Execution:
        used = self._conn.execute(
            "SELECT token_hmac FROM approvals WHERE proposal_id = ? AND used_at_turn IS NOT NULL",
            (proposal_id,),
        ).fetchone()
        tx = self._conn.execute(
            "SELECT transaction_id, approved_by FROM transactions WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if used is None or tx is None or not tokens_match(token, str(used[0])):
            raise ExecutionRefused(ExecutionRefusedReason.TOKEN_INVALID)
        return Execution(transaction_id=str(tx[0]), proposal_id=proposal_id, approved_by=str(tx[1]))
