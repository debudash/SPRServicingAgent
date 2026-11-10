"""case (code for B2): opens a case for a human (FR-04, FR-16, D-08, D-09).

The packet's free text is the already-masked turn, scrubbed a second time (ADR 0005), and fixed
wording; no model writes any of it in B2.
"""

import logging
import uuid
from typing import Any

from agents.guards.credentials import scrub
from agents.nodes.common import Deps, NodeFn, latest_customer_text
from contracts.messages import CasePacket, CaseReason, IntentKind
from contracts.ports import AuditEvent
from contracts.state import ConversationState, GateResult
from contracts.tools import Node, Step

logger = logging.getLogger(__name__)

_WHY: dict[CaseReason, tuple[str, str]] = {
    CaseReason.LOCKED: (
        "Session locked after three failed identity challenges.",
        "Contact the customer through a verified channel before any account action.",
    ),
    CaseReason.THIRD_PARTY: (
        "Someone other than the owner asked about or for action on the account.",
        "Verify the requester's authority offline, or contact the owner directly.",
    ),
}


def reason_for(state: ConversationState) -> CaseReason | None:
    if state.gate is GateResult.LOCKED_NOW:
        return CaseReason.LOCKED
    if state.intent is not None and state.intent.kind is IntentKind.THIRD_PARTY:
        return CaseReason.THIRD_PARTY
    return None


def make(deps: Deps) -> NodeFn:
    def case(state: ConversationState) -> dict[str, Any]:
        reason = reason_for(state)
        if reason is None:
            return {}
        summary, recommendation = _WHY[reason]
        packet = CasePacket(
            case_id=f"CASE-{uuid.uuid4().hex[:8].upper()}",
            conversation_id=state.conversation_id,
            customer_id=state.session.customer_id,
            opened_for=reason,
            request_summary=summary,
            quote=None,
            excerpt=scrub(latest_customer_text(state), state.as_of),
            recommendation=recommendation,
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
