"""transaction: quotes the amount the Concierge extracted and saves the proposal (ARCHITECTURE 3.3,
FR-05 to FR-07, #88).

Code, calling only the Transaction role's tools (get_account, quote, propose) through the registry,
which enforces that scope (FR-22). The figures come from the quote service, over records (GR-02);
respond formats them. Nothing here moves money: a proposal starts `quoted`, and only a later
explicit yes (confirm) and an approval (#89) take it further.
"""

import uuid
from typing import Any

from agents.nodes.common import Deps, NodeFn, is_live
from contracts.messages import (
    AccountView,
    Proposal,
    ProposalStatus,
    Quote,
    QuoteRefusal,
    proposal_hash,
)
from contracts.ports import AuditEvent
from contracts.state import ConversationState
from contracts.tools import Node, Role, Step, ToolName


def make(deps: Deps) -> NodeFn:
    def call(step: Step, tool: ToolName, **kwargs: Any) -> Any:
        deps.turn.record(Node.TRANSACTION, step)
        deps.turn.spend_tool_call()
        return deps.registry.call(Role.TRANSACTION, tool, **kwargs)

    def void_superseded(state: ConversationState) -> None:
        """GR-18: a new quote replaces the old one; that one can never be confirmed or approved."""
        old = state.proposal
        if old is not None and is_live(deps.proposals, old):
            deps.proposals.move(old.proposal_id, ProposalStatus.VOIDED)

    def transaction(state: ConversationState) -> dict[str, Any]:
        customer_id = state.session.customer_id
        intent = state.intent
        if customer_id is None or intent is None or intent.amount_cents is None:
            return {}  # no amount: respond asks for one, nothing is quoted
        view: AccountView = call(
            Step.GET_ACCOUNT, ToolName.GET_ACCOUNT, customer_id=customer_id, as_of=state.as_of
        )
        deps.turn.quote_basis = view
        result: Quote | QuoteRefusal = call(
            Step.QUOTE,
            ToolName.QUOTE,
            customer_id=customer_id,
            amount_cents=intent.amount_cents,
            as_of=state.as_of,
        )
        if isinstance(result, QuoteRefusal):  # FR-07: refused with the reason, nothing saved
            deps.turn.quote_refusal = result.reason
            # Issue #130: only a successful quote voided the one it replaced, so after a refused
            # new amount the old quote stayed live, its yes still waited for the step-up, and a
            # bare "yes" confirmed it. Asking for a new amount supersedes the old quote, whatever
            # the new quote's outcome (GR-17, GR-18).
            void_superseded(state)
            return {}
        proposal = Proposal(
            proposal_id=f"prop-{uuid.uuid4().hex[:12]}",
            conversation_id=state.conversation_id,
            customer_id=customer_id,
            quote=result,
            as_of=state.as_of,
            quoted_turn=state.turn,
            hash=proposal_hash(customer_id, result, state.as_of),
        )
        # Issue #131: the old proposal was voided before the new one was saved, so a failed save
        # left neither live while the old yes still waited for the step-up. Save first: a failed
        # turn then changes nothing.
        call(Step.PROPOSE, ToolName.PROPOSE, proposal=proposal)
        void_superseded(state)
        deps.audit.append(
            conversation_id=state.conversation_id,
            turn=state.turn,
            node=Node.TRANSACTION,
            event=AuditEvent.QUOTE_SHOWN,
            payload={
                "proposal_id": proposal.proposal_id,
                "amount_cents": result.amount_cents,
                "threshold_tier": result.threshold_tier.value,
            },
            versions=state.versions.model_dump(mode="json"),
        )
        return {"proposal": proposal}

    return transaction
