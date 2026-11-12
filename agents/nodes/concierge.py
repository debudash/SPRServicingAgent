"""concierge: classifies the latest message into an Intent. No tools (ADR 0005)."""

import re
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

# A dollar amount as customers type it: 5000, 5,000, $5,000.00, 26,000, 10k.
_AMOUNT = re.compile(r"(?<![\w.])\$?\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s?([kK])?(?![\w])")


def amounts_in(text: str) -> set[int]:
    """Every dollar amount written with digits in `text`, in cents."""
    found: set[int] = set()
    for whole, cents, k in _AMOUNT.findall(text):
        value = int(whole.replace(",", "")) * 100 + int((cents or "0").ljust(2, "0"))
        found.add(value * 1000 if k else value)
    return found


def checked_amount(intent: Intent, text: str) -> Intent:
    """Issue #191: the model's amount is used only if the customer typed it.

    With a quote in context the model adjusted "5000" to 450000 cents ($5,000 less 10%), and the
    desk quoted an amount nobody asked for. Numbers come from code, not the model (GR-02): the
    amount must be one the customer wrote. If it isn't, the one amount they wrote is used, or none
    when they wrote several (the desk then asks). Amounts in words, with no digits, keep the
    model's reading.
    """
    typed = amounts_in(text)
    if intent.amount_cents is None or not typed or intent.amount_cents in typed:
        return intent
    only = next(iter(typed)) if len(typed) == 1 else None
    return intent.model_copy(update={"amount_cents": only})


def make(deps: Deps) -> NodeFn:
    system, _version = load("concierge")

    def concierge(state: ConversationState) -> dict[str, Any]:
        text = latest_customer_text(state)
        messages = build_messages(system, session_context(state), [HumanMessage(content=text)])
        try:
            intent = invoke_structured(deps.models[Role.CONCIERGE], Intent, messages, deps.turn)
        except Exception:
            deps.turn.provider_error = True
            deps.turn.failure = "model_error"
            return {}
        return {"intent": checked_amount(intent, text)}

    return concierge
