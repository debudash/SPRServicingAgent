"""approval (code): the approval edge (GR-18, FR-08, ARCHITECTURE 3.3, #89).

Only Compliance's approve, on a proposal the rules left unflagged and in the self-service tier,
issues a token: HMAC over the proposal ID and hash, bound to that exact proposal. Hold and
escalate are recorded too (the store moves the proposal to escalated) and go to a case. The
ApprovalStore re-checks every rule (confirmed, self-service, the customer's yes) and refuses
anything else; a refusal ends the turn with nothing executed.
"""

import logging
import uuid
from typing import Any

from agents.nodes.common import Deps, NodeFn
from contracts.messages import Approval, Decision, ThresholdTier
from contracts.ports import AuditEvent
from contracts.state import ConversationState
from contracts.tools import Node

logger = logging.getLogger(__name__)


def make(deps: Deps) -> NodeFn:
    def approval(state: ConversationState) -> dict[str, Any]:
        proposal, review, money = state.proposal, state.compliance, deps.money
        if proposal is None or review is None or money is None:
            return {}
        decision = review.decision
        flagged = state.rule_flags is not None and bool(state.rule_flags.flags)
        human_tier = proposal.quote.threshold_tier is not ThresholdTier.SELF_SERVICE
        if decision is Decision.APPROVE and (flagged or human_tier):  # never reached; code says no
            decision = Decision.ESCALATE
        try:
            token = (
                money.issue_token(proposal.proposal_id, proposal.hash)
                if decision is Decision.APPROVE
                else None
            )
            recorded = Approval(
                approval_id=f"appr-{uuid.uuid4().hex[:12]}",
                proposal_id=proposal.proposal_id,
                approver="compliance",
                decision=decision,
                token_hmac=token,
            )
            money.approvals.record(recorded)
        except Exception:  # an empty secret, or the store refused: nothing is approved
            logger.exception("approval could not be recorded")
            deps.turn.failure = "approval_refused"
            return {}
        if token is not None:
            deps.audit.append(
                conversation_id=state.conversation_id,
                turn=state.turn,
                node=Node.APPROVAL,
                event=AuditEvent.TOKEN_ISSUED,
                # The approval's ID, never the token itself (it is the authority to move money).
                payload={"proposal_id": proposal.proposal_id, "approval_id": recorded.approval_id},
                versions=state.versions.model_dump(mode="json"),
            )
        return {"approval": recorded}

    return approval
