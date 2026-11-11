"""case (code for B2): opens a case for a human (FR-04, FR-16, D-08, D-09).

The packet's free text is the conversation's already-masked customer turns, scrubbed a second
time (ADR 0005), and fixed wording; no model writes any of it in B2.
"""

import logging
import uuid
from typing import Any

from agents.guards.credentials import scrub
from agents.nodes.common import Deps, NodeFn, is_live
from contracts.messages import (
    CasePacket,
    CaseReason,
    Decision,
    IntentKind,
    ProposalStatus,
    ThresholdTier,
)
from contracts.ports import AuditEvent
from contracts.state import ConversationState, GateResult
from contracts.tools import Node, Step

logger = logging.getLogger(__name__)

EXCERPT_TURNS = 5


def excerpt(state: ConversationState) -> str:
    """FR-16: the conversation's last customer turns, already masked, scrubbed once more."""
    said = [e.text for e in state.transcript if e.role == "customer"][-EXCERPT_TURNS:]
    return scrub(" | ".join(said), state.as_of)


_WHY: dict[CaseReason, tuple[str, str]] = {
    CaseReason.LOCKED: (
        "Session locked after three failed identity challenges.",
        "Contact the customer through a verified channel before any account action.",
    ),
    CaseReason.THIRD_PARTY: (
        "Someone other than the owner asked about or for action on the account.",
        "Verify the requester's authority offline, or contact the owner directly.",
    ),
    CaseReason.WITHDRAWAL_REVIEW: (
        "A withdrawal needs a person's review: see the rule flags and Compliance's decision.",
        "Review the proposal and its quote, then approve or reject it.",
    ),
    # 0.6.2 (B4): requests only a person decides; no money moves through the desk for these.
    CaseReason.WAIVER_REQUEST: (
        "The customer asked for a surrender-charge waiver (terminal illness, death benefit, RMD).",
        "Request the documentation the waiver needs; only a person grants a waiver (D-03, NG-01).",
    ),
    CaseReason.HARDSHIP: (
        "The customer described a hardship; there is no general hardship waiver.",
        "Contact the customer to discuss their options; do not imply a waiver (FR-14).",
    ),
    CaseReason.RMD: (
        "The customer asked about a required minimum distribution.",
        "Confirm the RMD amount and its charge treatment with the customer (FR-15).",
    ),
    CaseReason.FULL_SURRENDER: (
        "The customer asked to surrender the whole contract.",
        "Contact the customer before any full surrender; the desk never processes one (NG-07).",
    ),
}


def needs_review(state: ConversationState) -> bool:
    """#89: this turn sent the proposal to a person. The rules flagged it (D-02, D-07, FR-26),
    Compliance held or escalated it (FR-11, FR-12), or the customer asked to go ahead with a
    human-tier quote in the quoting turn (GR-19, BH-B3-05). Each is this turn's own result."""
    proposal = state.proposal
    if proposal is None:
        return False
    flags = state.rule_flags
    if flags is not None and flags.proposal_id == proposal.proposal_id and flags.flags:
        return True
    review = state.approval
    if (
        review is not None
        and review.proposal_id == proposal.proposal_id
        and review.decision in (Decision.HOLD, Decision.ESCALATE)
    ):
        return True
    intent = state.intent
    return (
        proposal.quoted_turn == state.turn
        and proposal.quote.threshold_tier is ThresholdTier.HUMAN
        and intent is not None
        and intent.explicit_yes
    )


def reason_for(state: ConversationState) -> CaseReason | None:
    """Why this turn opens a case, or None. The one place the rule lives (routing and respond
    ask here): a case names its customer (contracts 0.4.0), so no account bound means no case."""
    if state.session.customer_id is None:
        return None
    if state.gate is GateResult.LOCKED_NOW:
        return CaseReason.LOCKED
    if state.intent is not None and state.intent.kind is IntentKind.THIRD_PARTY:
        return CaseReason.THIRD_PARTY
    if needs_review(state):
        return CaseReason.WITHDRAWAL_REVIEW
    # B4 (#146): a person decides waivers (D-03, NG-01), RMDs (FR-15) and full surrenders (NG-07).
    if state.intent is not None:
        return _REQUEST_REASONS.get(state.intent.kind)
    return None


# Issue #152 (found by /code-review on PR #150): every hardship opened a waiver request, though
# the Concierge has one intent for terminal illness and any other hardship, and FR-14 says there
# is no general hardship waiver. It opens a hardship case; the documents' answer says which
# waivers exist (FR-13), and only a person decides (D-03, NG-01).
_REQUEST_REASONS = {
    IntentKind.HARDSHIP_WAIVER: CaseReason.HARDSHIP,
    IntentKind.RMD: CaseReason.RMD,
    IntentKind.FULL_SURRENDER: CaseReason.FULL_SURRENDER,
}


def make(deps: Deps) -> NodeFn:
    def case(state: ConversationState) -> dict[str, Any]:
        reason = reason_for(state)
        customer_id = state.session.customer_id
        if reason is None or customer_id is None:  # routing only sends a turn with a reason
            return {}
        summary, recommendation = _WHY[reason]
        review: dict[str, Any] = {}
        proposal = state.proposal
        if reason is CaseReason.WITHDRAWAL_REVIEW and proposal is not None:
            decision = state.compliance
            review = {
                "quote": proposal.quote,
                "proposal_id": proposal.proposal_id,
                "rule_flags": state.rule_flags.flags if state.rule_flags else frozenset(),
                # FR-23: the model's free text is scrubbed like the excerpt.
                "compliance_reasons": tuple(
                    r.model_copy(update={"text": scrub(r.text, state.as_of)})
                    for r in (decision.reasons if decision else ())
                ),
                "compliance_decision": decision.decision if decision else None,
                "signals": decision.signals if decision else frozenset(),
            }
            # With a person now: nothing on this path may confirm or approve it (the store
            # refuses Compliance once escalated). A recorded hold or escalate already moved it.
            if is_live(deps.proposals, proposal):
                deps.proposals.move(proposal.proposal_id, ProposalStatus.ESCALATED)
        packet = CasePacket(
            case_id=f"CASE-{uuid.uuid4().hex[:8].upper()}",
            conversation_id=state.conversation_id,
            customer_id=customer_id,
            opened_for=reason,
            request_summary=summary,
            quote=review.pop("quote", None),
            excerpt=excerpt(state),
            recommendation=recommendation,
            **review,
        )
        deps.turn.record(Node.CASE, Step.CREATE_CASE)
        # Issue #73 (found by /code-review on PR #72): a store error escaped the graph, and the
        # runner then discarded the whole turn, including the lock identity_gate had just
        # written, so the next try could pass (D-08). The node now fails closed inside the
        # graph: the turn is marked failed, no packet is returned, and the lock is saved.
        try:
            deps.cases.open(packet)
        except Exception:
            logger.exception("case could not be opened")
            deps.turn.failure = "case_unavailable"
            return {}
        deps.audit.append(
            conversation_id=state.conversation_id,
            turn=state.turn,
            node=Node.CASE,
            event=AuditEvent.CASE_OPENED,
            payload={"opened_for": reason.value},
            versions=state.versions.model_dump(mode="json"),
            case_id=packet.case_id,
        )
        return {"case_packet": packet}

    return case
