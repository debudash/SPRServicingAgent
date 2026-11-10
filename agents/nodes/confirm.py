"""confirm (code): the customer's explicit yes to the quote shown (GR-17, FR-08, #88).

A yes counts only when the Concierge read an unambiguous yes, for the quoted amount (or no amount,
which can only mean the one quoted), on a later turn than the quote, while the quote is still
waiting for its answer. `ProposalStore.confirm` checks the same rule again (`check_confirmation`).
Anything else confirms nothing: respond asks for a clear yes, and routing has already sent a new
amount to the transaction node for a new quote.

It also runs after every quote: a yes given for an earlier quote must not wait for the step-up
once that quote is replaced (GR-18).
"""

from typing import Any

from agents.nodes.common import MONEY_INTENTS, Deps, NodeFn
from contracts.messages import Confirmation, ProposalStatus
from contracts.ports import AuditEvent
from contracts.state import ConversationState
from contracts.tools import Node


def make(deps: Deps) -> NodeFn:
    def confirm(state: ConversationState) -> dict[str, Any]:
        proposal, intent, earlier = state.proposal, state.intent, state.confirmation
        # Issue #130: a yes was cleared only when the proposal's ID changed, so a yes for a quote
        # voided in place (a refused new amount) kept waiting for the step-up. A yes stands only
        # while its proposal is still confirmed in the store.
        stale = earlier is not None and (
            proposal is None
            or earlier.proposal_id != proposal.proposal_id
            or deps.proposals.status(earlier.proposal_id) is not ProposalStatus.CONFIRMED
        )
        cleared: dict[str, Any] = {"confirmation": None} if stale else {}
        if proposal is None or intent is None or intent.kind not in MONEY_INTENTS:
            return cleared
        quoted = proposal.quote.amount_cents
        if not intent.explicit_yes or intent.amount_cents not in (None, quoted):
            return cleared
        if proposal.quoted_turn >= state.turn:  # GR-17: the yes comes after the quote
            return cleared
        if deps.proposals.status(proposal.proposal_id) is not ProposalStatus.QUOTED:
            return cleared  # already confirmed (a repeated yes), or no longer live
        yes = Confirmation(proposal_id=proposal.proposal_id, amount_cents=quoted, turn=state.turn)
        deps.proposals.confirm(yes, state.conversation_id)
        deps.audit.append(
            conversation_id=state.conversation_id,
            turn=state.turn,
            node=Node.CONFIRM,
            event=AuditEvent.CONFIRMED,
            payload={"proposal_id": proposal.proposal_id, "amount_cents": quoted},
            versions=state.versions.model_dump(mode="json"),
        )
        return {"confirmation": yes}

    return confirm
