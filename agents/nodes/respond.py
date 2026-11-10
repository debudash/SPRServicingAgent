"""respond: writes the Reply and the turn's one audit row (FR-10).

Replies are built by code from the structured results: the gate decision, the account view (GR-02:
figures straight from the record, formatted by `contracts.money`) or the case. No model writes them.
"""

from typing import Any

from agents.nodes.common import Deps, NodeFn
from contracts.messages import AccountView, IntentKind, Reply
from contracts.money import format_dollars
from contracts.outcomes import Outcome
from contracts.ports import AuditEvent
from contracts.state import MAX_FAILED_CHALLENGES, ConversationState, GateResult
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


CONTACT = "1-800-555-0192 (Mon-Fri, 8am-6pm CT)"
ASK_TEXT = (
    "Before I can discuss your account, I need to confirm it's you. Please give me your date of "
    "birth and the last four digits of your Social Security number."
)
UNTRUSTED_TEXT = (
    "I'm not able to service this account through the desk. Please call SPR Financials at "
    f"{CONTACT} and the team will help you."
)
NO_CUSTOMER_TEXT = (
    "Please sign in to your account first; I can only discuss the account you're signed in to. "
    "I'm happy to answer general questions about the SecureGrowth Fixed Annuity."
)
LOCKED_TEXT = (
    "For your security, account actions are locked for this session after too many unsuccessful "
    f"identity checks. Please call SPR Financials at {CONTACT}."
)
LOCKED_NO_CASE_TEXT = (
    "For your security, account actions are now locked for this session after three "
    "unsuccessful identity checks. I couldn't open a case for the team just now, so please call "
    f"SPR Financials at {CONTACT}."
)
OTHER_ACCOUNT_TEXT = (
    "I can only discuss the account you're signed in to. The owner of any other account would need "
    "to contact us themselves."
)
RESTRICTED_TEXT = (
    "For your security I never read back a date of birth or Social Security digits, even to the "
    f"account owner. If your details need checking, please call SPR Financials at {CONTACT}."
)


def _failed_text(attempts: int) -> str:
    left = MAX_FAILED_CHALLENGES - attempts
    tries = "try" if left == 1 else "tries"
    return (
        "Those details don't match our records, so I can't discuss the account yet. You have "
        f"{left} more {tries}: please give your date of birth and the last four digits of your SSN."
    )


def _account_text(view: AccountView) -> str:
    return (
        f"Your current balance is {format_dollars(view.balance_cents)}. You're in contract year "
        f"{view.contract_year}, and you can withdraw up to "
        f"{format_dollars(view.allowance_remaining_cents)} more this contract year without a "
        "surrender charge."
    )


def _case_text(case_id: str, locked: bool) -> str:
    if locked:
        return (
            "For your security, account actions are now locked for this session after three "
            f"unsuccessful identity checks. I've opened case {case_id} so the team can contact "
            f"you, or you can call SPR Financials at {CONTACT}."
        )
    return (
        "I can only discuss an account or act on it with its owner. I've opened case "
        f"{case_id} so the team can confirm your authority offline. I'm happy to answer general "
        "questions about the SecureGrowth Fixed Annuity in the meantime."
    )


def decide(state: ConversationState, failure: str | None) -> tuple[Outcome, str, str | None]:
    """The turn's outcome, the reply text and the reference (a case ID) shown to the customer."""
    if state.gate is GateResult.LOCKED_NOW and state.case_packet is None:
        # Issue #73: the lock holds even when the case could not be opened; say so (GR-21).
        return Outcome.NOT_PERMITTED, LOCKED_NO_CASE_TEXT, None
    if failure is not None or state.intent is None:
        return Outcome.UNAVAILABLE, UNAVAILABLE_TEXT, None
    kind = state.intent.kind
    packet = state.case_packet
    if packet is not None:
        locked = state.gate is GateResult.LOCKED_NOW
        outcome = Outcome.NOT_PERMITTED if locked else Outcome.NEEDS_HUMAN
        return outcome, _case_text(packet.case_id, locked), packet.case_id
    if kind is IntentKind.THIRD_PARTY:  # routed to a case that was not opened: fail closed
        return Outcome.UNAVAILABLE, UNAVAILABLE_TEXT, None
    if kind is IntentKind.OTHER_ACCOUNT:
        return Outcome.NOT_PERMITTED, OTHER_ACCOUNT_TEXT, None
    if kind is IntentKind.RESTRICTED_INFO:
        return Outcome.NOT_PERMITTED, RESTRICTED_TEXT, None
    gate = state.gate
    if gate is not None:
        return _after_gate(state, gate)
    if kind is IntentKind.PRODUCT_QUESTION:
        answer = state.knowledge_answer
        if answer is None:
            return Outcome.UNAVAILABLE, UNAVAILABLE_TEXT, None
        if answer.found:
            return Outcome.ANSWERED, answer.text, None
        return Outcome.NO_SOURCE, answer.text, None
    if kind is IntentKind.OUT_OF_SCOPE:
        return Outcome.OUT_OF_SCOPE, OUT_OF_SCOPE_TEXT, None
    return Outcome.NOT_PERMITTED, NOT_YET_TEXT, None


def _after_gate(state: ConversationState, gate: GateResult) -> tuple[Outcome, str, str | None]:
    refusals = {
        GateResult.NO_CUSTOMER: NO_CUSTOMER_TEXT,
        GateResult.UNTRUSTED: UNTRUSTED_TEXT,
        GateResult.LOCKED: LOCKED_TEXT,
        GateResult.ASK: ASK_TEXT,
    }
    if gate in refusals:
        return Outcome.NOT_PERMITTED, refusals[gate], None
    if gate is GateResult.FAILED:
        return Outcome.NOT_PERMITTED, _failed_text(state.session.failed_attempts), None
    if state.account_view is not None:  # PASSED or VERIFIED, and the account was read
        return Outcome.ANSWERED, _account_text(state.account_view), None
    if gate is GateResult.PASSED:
        return Outcome.ANSWERED, "Thank you, you're verified. " + NOT_YET_TEXT, None
    return Outcome.NOT_PERMITTED, NOT_YET_TEXT, None


def make(deps: Deps) -> NodeFn:
    def respond(state: ConversationState) -> dict[str, Any]:
        outcome, text, reference = decide(state, deps.turn.failure)
        reply = Reply(text=text, outcome=outcome, reference=reference)
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
                "gate": state.gate.value if state.gate else None,
                "citations": [c.model_dump(mode="json") for c in citations],
                "steps": [s.value for s in deps.turn.steps],
            },
            versions=versions,
            case_id=reference,
        )
        deps.turn.audited = True
        return {"reply": reply}

    return respond
