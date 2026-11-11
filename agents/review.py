"""The reviewer's side of the desk (B4, FR-17, ARCHITECTURE 3.4; contracts 0.6.2 ReviewDesk, #146).

A person decides a case. On a withdrawal review, approve runs the same money path as B3: a token
bound to that proposal's hash, recorded as the reviewer's approval, then one execution through
the ledger (FR-08 to FR-10, GR-18). The stores re-check every rule: a reviewer approves only an
escalated proposal the customer confirmed, and the ledger still honours the kill switch (FR-26).
Cases with no proposal (locked, third party, waiver, hardship, RMD, full surrender) record the
decision; no money moves through the desk for them (NG-01, NG-07).

Code, no model: the decision is the person's, and every guard is the one B3 already tests.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import date

from pydantic import JsonValue

from agents.nodes.common import MoneyPath
from agents.nodes.execute import versions_cited
from contracts import CONTRACTS_VERSION
from contracts.messages import (
    CASE_DECIDABLE,
    Approval,
    CasePacket,
    CaseStatus,
    CaseSummary,
    Decision,
    HumanDecision,
    ProposalStatus,
    ReviewResult,
)
from contracts.outcomes import Outcome
from contracts.ports import AuditEvent, AuditLog, CaseReview, ExecutionRefused, ProposalStore
from contracts.tools import Node

logger = logging.getLogger(__name__)


def _money(dollars_cents: int) -> str:
    return f"${dollars_cents / 100:,.2f}"


class AgentReviewDesk:
    def __init__(
        self,
        cases: CaseReview,
        proposals: ProposalStore,
        money: MoneyPath,
        audit: AuditLog,
        clock: Callable[[], date],
    ) -> None:
        self._cases = cases
        self._proposals = proposals
        self._money = money
        self._audit = audit
        self._clock = clock

    def queue(
        self, status: CaseStatus | None = None, customer_id: str | None = None
    ) -> list[CaseSummary]:
        return self._cases.list_cases(status, customer_id)

    def case(self, case_id: str) -> CasePacket | None:
        return self._cases.get(case_id)

    def decide(self, decision: HumanDecision) -> ReviewResult:
        current = self._cases.status(decision.case_id)  # KeyError for an unknown case
        if current not in CASE_DECIDABLE:
            raise ValueError(f"case {decision.case_id} is already {current.value}")
        packet = self._cases.get(decision.case_id)
        assert packet is not None  # it has a status, so it exists
        if packet.proposal_id is None:
            return self._record_only(packet, decision)
        if decision.decision is Decision.APPROVE:
            return self._approve(packet, packet.proposal_id, decision)
        return self._refuse_or_ask(packet, packet.proposal_id, decision)

    # ---------- a case with no proposal: the decision is recorded, nothing moves ----------
    def _record_only(self, packet: CasePacket, decision: HumanDecision) -> ReviewResult:
        self._cases.decide(decision)
        self._log(packet, decision, {})
        texts = {
            Decision.APPROVE: "Decision recorded. Follow up with the customer outside the desk; "
            "no money moves here for this case.",
            Decision.REJECT: "Request declined and recorded.",
            Decision.REQUEST_INFO: "Marked as waiting for information from the customer.",
        }
        outcomes = {
            Decision.APPROVE: Outcome.ANSWERED,
            Decision.REJECT: Outcome.NOT_PERMITTED,
            Decision.REQUEST_INFO: Outcome.NEEDS_HUMAN,
        }
        return ReviewResult(
            case_id=packet.case_id,
            decision=decision.decision,
            outcome=outcomes[decision.decision],
            reference=packet.case_id,
            text=texts[decision.decision],
        )

    # ---------- approve a withdrawal: the B3 path, with the reviewer as approver ----------
    def _approve(self, packet: CasePacket, pid: str, decision: HumanDecision) -> ReviewResult:
        proposal = self._proposals.get(pid)
        if proposal is None:
            raise KeyError(pid)
        status = self._proposals.status(pid)
        if status is not ProposalStatus.ESCALATED:
            return self._not_done(packet, decision, f"the withdrawal is {status.value}, not open")
        try:
            token = self._money.issue_token(pid, proposal.hash)
            approval = Approval(
                approval_id=f"appr-{uuid.uuid4().hex[:12]}",
                proposal_id=pid,
                approver=f"human:{decision.reviewer_id}",
                decision=Decision.APPROVE,
                token_hmac=token,
            )
            self._money.approvals.record(approval)  # the store re-checks: confirmed, escalated
        except ValueError as refused:  # never confirmed (GR-17), or no approval secret
            logger.warning("reviewer approval refused: %s", refused)
            return self._not_done(packet, decision, str(refused))
        cited: dict[str, JsonValue] = dict(versions_cited(packet.compliance_reasons))
        versions: dict[str, JsonValue] = {
            "contracts": CONTRACTS_VERSION,
            "documents": cited,
        }  # FR-10
        try:
            done = self._money.ledger.execute(pid, token, self._turn(packet), versions)
        except (ExecutionRefused, ValueError) as refused:
            # Nothing moved. The approval is spent: the withdrawal goes back to the person, and
            # the case stays open with the reason (FR-26, GR-21).
            logger.warning("execution refused after a reviewer's approval: %s", refused)
            if self._proposals.status(pid) is ProposalStatus.APPROVED:
                self._proposals.move(pid, ProposalStatus.ESCALATED)
            return self._not_done(packet, decision, f"the ledger refused it ({refused})")
        self._cases.decide(decision)
        self._log(packet, decision, {"proposal_id": pid, "transaction_id": done.transaction_id})
        return ReviewResult(
            case_id=packet.case_id,
            decision=Decision.APPROVE,
            outcome=Outcome.EXECUTED,
            reference=done.transaction_id,
            text=(
                f"Approved by {decision.reviewer_id} and executed: "
                f"{_money(proposal.quote.amount_cents)} gross, "
                f"{_money(proposal.quote.net_cents)} to the customer. "
                f"Confirmation {done.transaction_id}."
            ),
        )

    # ---------- reject or ask for information on a withdrawal ----------
    def _refuse_or_ask(self, packet: CasePacket, pid: str, decision: HumanDecision) -> ReviewResult:
        status = self._proposals.status(pid)
        # Issue #151 (found by /code-review on PR #150): the case was marked rejected whatever the
        # withdrawal's state, so a reject landed on one already approved (racing an approval) or
        # executed. Only a withdrawal still with the person (or already void, for a reject) can
        # be rejected or put on hold for information; anything else is refused unwritten.
        allowed = {ProposalStatus.ESCALATED}
        if decision.decision is Decision.REJECT:
            allowed.add(ProposalStatus.VOIDED)
        if status not in allowed:
            return self._not_done(packet, decision, f"the withdrawal is already {status.value}")
        if status is ProposalStatus.ESCALATED:
            self._money.approvals.record(
                Approval(
                    approval_id=f"appr-{uuid.uuid4().hex[:12]}",
                    proposal_id=pid,
                    approver=f"human:{decision.reviewer_id}",
                    decision=decision.decision,  # reject voids it; request_info leaves it
                )
            )
        self._cases.decide(decision)
        self._log(packet, decision, {"proposal_id": pid})
        if decision.decision is Decision.REJECT:
            return ReviewResult(
                case_id=packet.case_id,
                decision=Decision.REJECT,
                outcome=Outcome.NOT_PERMITTED,
                reference=packet.case_id,
                text="Withdrawal rejected; nothing was withdrawn.",
            )
        return ReviewResult(
            case_id=packet.case_id,
            decision=Decision.REQUEST_INFO,
            outcome=Outcome.NEEDS_HUMAN,
            reference=packet.case_id,
            text="Waiting for information from the customer; nothing was withdrawn.",
        )

    # ---------- helpers ----------
    def _not_done(self, packet: CasePacket, decision: HumanDecision, why: str) -> ReviewResult:
        """The decision could not take effect: the case stays as it was."""
        return ReviewResult(
            case_id=packet.case_id,
            decision=decision.decision,
            outcome=Outcome.NOT_PERMITTED,
            reference=packet.case_id,
            text=f"Not done: {why}. The case stays open.",
        )

    def _turn(self, packet: CasePacket) -> int:
        """The conversation's latest audited turn: the reviewer acts after it."""
        rows = self._audit.read(packet.conversation_id)
        return max((r.turn for r in rows), default=1)

    def _log(self, packet: CasePacket, decision: HumanDecision, extra: dict[str, str]) -> None:
        self._audit.append(
            conversation_id=packet.conversation_id,
            turn=self._turn(packet),
            node=Node.HUMAN_REVIEW,
            event=AuditEvent.HUMAN_DECIDED,
            payload={
                "case_id": packet.case_id,
                "decision": decision.decision.value,
                "reviewer": f"human:{decision.reviewer_id}",
                **extra,
            },
            versions={"contracts": CONTRACTS_VERSION},
            case_id=packet.case_id,
        )
