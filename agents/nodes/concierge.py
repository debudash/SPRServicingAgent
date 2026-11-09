"""concierge: classifies the latest message into an Intent. No tools (ADR 0005)."""

from typing import Any

from langchain_core.messages import HumanMessage

from agents.llm import build_messages
from agents.nodes.common import (
    Deps,
    NodeFn,
    invoke_structured,
    latest_customer_text,
    session_context,
)
from agents.prompts import load
from contracts.messages import Intent
from contracts.state import ConversationState
from contracts.tools import Role


def make(deps: Deps) -> NodeFn:
    system, _version = load("concierge")

    def concierge(state: ConversationState) -> dict[str, Any]:
        messages = build_messages(
            system, session_context(state), [HumanMessage(content=latest_customer_text(state))]
        )
        try:
            intent = invoke_structured(deps.models[Role.CONCIERGE], Intent, messages, deps.turn)
        except Exception:
            deps.turn.provider_error = True
            deps.turn.failure = "model_error"
            return {}
        return {"intent": intent}

    return concierge
