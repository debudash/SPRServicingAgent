"""respond: writes the Reply and the turn's one audit row (FR-10).

B1 replies are built by code from the structured result, so no model call is needed to say
"not available yet". The respond prompt is used once replies carry figures (later bullets).
"""

from typing import Any

from agents.nodes.common import Deps, NodeFn
from contracts.messages import IntentKind, Reply
from contracts.outcomes import Outcome
from contracts.ports import AuditEvent
from contracts.state import ConversationState
from contracts.tools import Node

OUT_OF_SCOPE_TEXT = (
    "I can only help with the SecureGrowth Fixed Annuity, and I can't give advice on other "
    "products or on where to put your money."
)
NOT_YET_TEXT = (
    "That isn't available through this desk yet. I can answer questions about the "
    "SecureGrowth Fixed Annuity."
)
UNAVAILABLE_TEXT = (
    "I couldn't complete that just now, and nothing has been changed. Please try again shortly."
)


def decide(state: ConversationState, failure: str | None) -> tuple[Outcome, str]:
    if failure is not None or state.intent is None:
        return Outcome.UNAVAILABLE, UNAVAILABLE_TEXT
    kind = state.intent.kind
    if kind is IntentKind.PRODUCT_QUESTION:
        answer = state.knowledge_answer
        if answer is None:
            return Outcome.UNAVAILABLE, UNAVAILABLE_TEXT
        if answer.found:
            return Outcome.ANSWERED, answer.text
        return Outcome.NO_SOURCE, answer.text
    if kind is IntentKind.OUT_OF_SCOPE:
        return Outcome.OUT_OF_SCOPE, OUT_OF_SCOPE_TEXT
    return Outcome.NOT_PERMITTED, NOT_YET_TEXT


def make(deps: Deps) -> NodeFn:
    def respond(state: ConversationState) -> dict[str, Any]:
        outcome, text = decide(state, deps.turn.failure)
        reply = Reply(text=text, outcome=outcome)
        answered = outcome is Outcome.ANSWERED
        citations = (
            state.knowledge_answer.citations
            if answered and state.knowledge_answer is not None
            else ()
        )
        versions = state.versions.model_dump(mode="json")
        versions["documents"] = {c.doc_id: c.version for c in citations}
        deps.audit.append(
            conversation_id=state.conversation_id,
            turn=state.turn,
            node=Node.RESPOND,
            event=AuditEvent.ANSWERED if answered else AuditEvent.REFUSED,
            payload={
                "outcome": outcome.value,
                "intent": state.intent.kind.value if state.intent else None,
                "citations": [c.model_dump(mode="json") for c in citations],
                "steps": [s.value for s in deps.turn.steps],
            },
            versions=versions,
        )
        deps.turn.audited = True
        return {"reply": reply}

    return respond
