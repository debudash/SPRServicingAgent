"""respond: writes the Reply and the turn's one audit row (FR-10).

Replies are built by code from the structured results: the gate decision, the account view (GR-02:
figures straight from the record, formatted by `contracts.money`), the quote (#88) or the case. No
model writes them.
"""

from dataclasses import dataclass
from typing import Any

from agents.nodes import case
from agents.nodes.common import (
    ACCOUNT_INTENTS,
    MONEY_INTENTS,
    REQUEST_INTENTS,
    Deps,
    NodeFn,
    is_live,
    shown_citations,
)
from contracts.messages import (
    AccountView,
    CaseReason,
    IntentKind,
    Quote,
    QuoteRefusalReason,
    Reply,
    ThresholdTier,
)
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
HELLO_TEXT = (
    "Hello! I'm the SecureGrowth Fixed Annuity servicing desk. I can answer questions about the "
    "annuity, show your balance and contract details once you're logged in, and quote a "
    "withdrawal. What would you like to do?"
)
UNAVAILABLE_TEXT = (
    "I couldn't complete that just now, and nothing has been changed. Please try again shortly."
)


CONTACT = "1-800-555-0192 (Mon-Fri, 8am-6pm CT)"
# ADR 0007: nothing asks for a date of birth or SSN digits in chat. A session bound without a
# login is asked to log in; the step-up check has its own form.
ASK_TEXT = (
    "Please log in to your account first, so I can discuss it with you. I'm happy to answer "
    "general questions about the SecureGrowth Fixed Annuity."
)
UNTRUSTED_TEXT = (
    "I'm not able to service this account through the desk. Please call SPR Financials at "
    f"{CONTACT} and the team will help you."
)
NO_CUSTOMER_TEXT = (
    "Please log in to your account first; I can only discuss the account you're logged in to. "
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
NO_ACCOUNT_THIRD_PARTY_TEXT = (
    "I can only discuss an account, or act on it, with its owner. The owner can contact SPR "
    f"Financials at {CONTACT}. I'm happy to answer general questions about the SecureGrowth "
    "Fixed Annuity."
)
OTHER_ACCOUNT_TEXT = (
    "I can only discuss the account you're logged in to. The owner of any other account would need "
    "to contact us themselves."
)
RESTRICTED_TEXT = (
    "For your security I never read back a date of birth or Social Security digits, even to the "
    f"account owner. If your details need checking, please call SPR Financials at {CONTACT}."
)


STEP_UP_PASSED_TEXT = "Thank you, that's confirmed."
NO_STEP_UP_TEXT = "There's nothing waiting for an identity check right now, so nothing was checked."
STEP_UP_INCOMPLETE_TEXT = (
    "Please give your date of birth and the four digits of your SSN; nothing was checked."
)


# ---------- #88: quotes and the yes ----------
ASK_AMOUNT_TEXT = (
    "How much would you like to withdraw? I'll show you an exact quote before anything happens."
)
NOTHING_TO_CONFIRM_TEXT = (
    "There's no quote waiting for your answer, so nothing has been confirmed. Tell me how much "
    "you'd like to withdraw and I'll quote it first."
)
STEP_UP_NEEDED_TEXT = (
    "Thank you. Before any money moves, please complete the identity check. Nothing has been "
    "withdrawn yet."
)
NOT_POSITIVE_TEXT = (
    "I can only quote an amount greater than zero. How much would you like to withdraw?"
)
NOT_ACTIVE_TEXT = (
    "I can't quote a withdrawal on this account because it isn't active. Please call SPR "
    f"Financials at {CONTACT}."
)


@dataclass(frozen=True)
class MoneyFacts:
    """What respond needs about the money path beyond the state: this turn's refused quote and the
    account it was quoted against (TurnContext), and whether the proposal is still live."""

    refusal: QuoteRefusalReason | None = None
    basis: AccountView | None = None
    live: bool = False


NO_MONEY = MoneyFacts()


def _rate(rate_bp: int) -> str:
    return f"{rate_bp / 100:g}%"


def quote_text(quote: Quote, basis: AccountView | None) -> str:
    """The quote, every figure from the Quote (GR-02), formatted here. The IRS notice is
    information (FR-06, GR-08); the human tier is said up front (D-02)."""
    amount = format_dollars(quote.amount_cents)
    lead = f"Here's your quote for withdrawing {amount}"
    if basis is not None:
        lead += (
            f", based on your current balance of {format_dollars(basis.balance_cents)} in "
            f"contract year {quote.contract_year}"
        )
    lines = [
        f"{lead}:",
        f"- Free withdrawal allowance left this contract year: {format_dollars(quote.free_cents)}",
        f"- Amount above the allowance: {format_dollars(quote.excess_cents)}",
        f"- Surrender charge at {_rate(quote.rate_bp)} of that amount: "
        f"{format_dollars(quote.charge_cents)}",
        f"- You would receive: {format_dollars(quote.net_cents)}",
    ]
    if quote.irs_notice:
        lines.append(
            "Because you're under age 59½, the IRS may also apply a 10% early withdrawal penalty. "
            "That's a federal tax matter, not an SPR Financials fee; a tax advisor can explain how "
            "it applies to you."
        )
    if quote.threshold_tier is ThresholdTier.HUMAN:
        lines.append("A withdrawal of this size is reviewed by our team before it's paid.")
    lines.append(
        "Nothing has been withdrawn. If you'd like to go ahead, reply with a clear yes for "
        f"{amount}."
    )
    return "\n".join(lines)


def _refusal_text(
    reason: QuoteRefusalReason, amount_cents: int | None, basis: AccountView | None
) -> str:
    """FR-07: the reason, in words, and the next step (GR-20)."""
    if reason is QuoteRefusalReason.NOT_ACTIVE:
        return NOT_ACTIVE_TEXT
    if reason is QuoteRefusalReason.NOT_POSITIVE or amount_cents is None:
        return NOT_POSITIVE_TEXT
    balance = f" of {format_dollars(basis.balance_cents)}" if basis is not None else ""
    return (
        f"I can't quote a withdrawal of {format_dollars(amount_cents)}: it's more than your "
        f"current balance{balance}. Nothing has been withdrawn."
    )


def _clear_yes_text(amount_cents: int) -> str:
    amount = format_dollars(amount_cents)
    return (
        f"To go ahead with the withdrawal of {amount}, I need a clear yes for that amount. "
        "Nothing has been withdrawn."
    )


def _executed_text(quote: Quote, reference: str) -> str:
    """GR-10: said only when the ledger returned an Execution (#89)."""
    return (
        f"Done. Your withdrawal of {format_dollars(quote.amount_cents)} is complete. You'll "
        f"receive {format_dollars(quote.net_cents)} after a surrender charge of "
        f"{format_dollars(quote.charge_cents)}. Your reference is {reference}."
    )


def _review_text(case_id: str) -> str:
    """#89: a person reviews this withdrawal; nothing has moved (GR-19, FR-26)."""
    return (
        # #183 (owner): say plainly that it is submitted, nothing is paid, and who acts next.
        f"Your withdrawal request has been submitted for review (case {case_id}). Nothing has "
        "been paid yet. A member of our team will reach out to you once the review is complete, "
        'and you can check its status under "Your cases" whenever you log in.'
    )


def _money_result(
    state: ConversationState, money: MoneyFacts, show_quote: bool = True
) -> tuple[Outcome, str, str | None] | None:
    """#89: the withdrawal executed this turn, or went to a person; None when neither."""
    proposal, done, packet = state.proposal, state.execution, state.case_packet
    if done is not None and proposal is not None and done.proposal_id == proposal.proposal_id:
        reference = done.transaction_id
        return Outcome.EXECUTED, _executed_text(proposal.quote, reference), reference
    if packet is not None and packet.opened_for is CaseReason.WITHDRAWAL_REVIEW:
        text = _review_text(packet.case_id)
        quoted_now = proposal is not None and proposal.quoted_turn == state.turn
        if show_quote and proposal is not None and quoted_now:  # BH-B3-05: the quote first
            text = quote_text(proposal.quote, money.basis) + "\n" + text
        return Outcome.NEEDS_HUMAN, text, packet.case_id
    return None


def _failed_text(attempts: int) -> str:
    left = MAX_FAILED_CHALLENGES - attempts
    tries = "try" if left == 1 else "tries"
    return (
        "Those details don't match our records. You have "
        f"{left} more {tries}: please fill in the identity check again."
    )


def _account_text(view: AccountView) -> str:
    # Issue #176: the reply was one balance template, so "when did my contract start?" got the
    # balance. The view now carries the start date (contracts 0.6.4) and the reply leads with it.
    start = view.contract_start_date
    began = f"Your contract started on {start:%B} {start.day}, {start.year}. " if start else ""
    return began + (
        f"Your current balance is {format_dollars(view.balance_cents)}. You're in contract year "
        f"{view.contract_year}, and you can withdraw up to "
        f"{format_dollars(view.allowance_remaining_cents)} more this contract year without a "
        "surrender charge."
    )


LOGIN_FOR_REQUEST_TEXT = (
    "A person on our team handles that request, and they need to know whose contract it is. "
    f"Please log in and ask again, or call SPR Financials at {CONTACT}."
)
_REQUEST_CASE_TEXT = {
    # Issue #152: never implies a waiver may apply (FR-14, NG-01); the documents' answer before
    # this says which waivers exist and what they need.
    IntentKind.HARDSHIP_WAIVER: (
        "There is no general hardship waiver: surrender charges are waived only in the cases our "
        "documents list. I've opened case {case_id} so a person on our team can go through your "
        "situation and options with you. Nothing has been waived or withdrawn."
    ),
    IntentKind.RMD: (
        "I've opened case {case_id} so a person on our team can confirm your required minimum "
        "distribution with you. Nothing has been withdrawn."
    ),
    IntentKind.FULL_SURRENDER: (
        "A full surrender is always handled by a person on our team, so nothing has been "
        "withdrawn. I've opened case {case_id}; they'll contact you to go through it."
    ),
}


def _request_text(state: ConversationState, case_id: str) -> str:
    """B4 (#146): the documents' answer, when there is one, then what happens next. Never says a
    waiver applies (FR-13, FR-14, NG-01)."""
    assert state.intent is not None
    then = _REQUEST_CASE_TEXT[state.intent.kind].format(case_id=case_id)
    answer = state.knowledge_answer
    if answer is not None and answer.found:
        return f"{answer.text}\n\n{then}"
    return then


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


def decide(
    state: ConversationState,
    failure: str | None,
    step_up: bool = False,
    money: MoneyFacts = NO_MONEY,
) -> tuple[Outcome, str, str | None]:
    """The turn's outcome, the reply text and the reference (a case ID) shown to the customer."""
    if step_up:
        return _after_step_up(state, failure, money)
    outcome, text, reference = _decide(state, failure, money)
    return outcome, _first_turn_notice(state) + text, reference


def _after_step_up(
    state: ConversationState, failure: str | None, money: MoneyFacts = NO_MONEY
) -> tuple[Outcome, str, str | None]:
    """A step-up turn (ADR 0007): the form's result. On a pass, #89 continues the withdrawal."""
    gate = state.gate
    if gate is GateResult.LOCKED_NOW:
        packet = state.case_packet
        if packet is None:  # issue #73: the lock holds even when the case could not be opened
            return Outcome.NOT_PERMITTED, LOCKED_NO_CASE_TEXT, None
        return Outcome.NOT_PERMITTED, _case_text(packet.case_id, locked=True), packet.case_id
    if failure is not None:
        return Outcome.UNAVAILABLE, UNAVAILABLE_TEXT, None
    if gate is GateResult.PASSED:
        # A step-up turn never shows a quote: the quote came on an earlier turn (GR-17).
        result = _money_result(state, money, show_quote=False)
        return result or (Outcome.ANSWERED, STEP_UP_PASSED_TEXT, None)
    if gate is GateResult.FAILED:
        return Outcome.NOT_PERMITTED, _failed_text(state.session.failed_attempts), None
    refusals: dict[GateResult | None, str] = {
        GateResult.UNTRUSTED: UNTRUSTED_TEXT,
        GateResult.LOCKED: LOCKED_TEXT,
        GateResult.ASK: ASK_TEXT,  # bound without a login: log in first (review on PR #113)
    }
    return Outcome.NOT_PERMITTED, refusals.get(gate, NO_STEP_UP_TEXT), None


def _first_turn_notice(state: ConversationState) -> str:
    """#82, FR-03: an untrusted account is told at the start, whatever the first turn asked.
    Not repeated when the gate already refused with the same notice."""
    s = state.session
    untrusted = s.customer_id is not None and not s.gate_a_trusted
    # Issue #84 (found by /code-review on PR #83): keyed on `turn == 1`, the notice was lost for
    # good when turn 1 failed before respond ran (e.g. the account store was down). "At the
    # start" is the desk's first reply built here, which the trace records: earlier turns' trace
    # holds a respond event only if respond ran in them.
    replied_before = any(e.node is Node.RESPOND for e in state.trace)
    if untrusted and not replied_before and state.gate is not GateResult.UNTRUSTED:
        return UNTRUSTED_TEXT + " "
    return ""


def _decide(
    state: ConversationState, failure: str | None, money: MoneyFacts
) -> tuple[Outcome, str, str | None]:
    if state.gate is GateResult.LOCKED_NOW and state.case_packet is None:
        # Issue #73: the lock holds even when the case could not be opened; say so (GR-21).
        return Outcome.NOT_PERMITTED, LOCKED_NO_CASE_TEXT, None
    if failure is not None or state.intent is None:
        return Outcome.UNAVAILABLE, UNAVAILABLE_TEXT, None
    kind = state.intent.kind
    result = _money_result(state, money)  # #89: executed, or with a person
    if result is not None:
        return result
    packet = state.case_packet
    if packet is not None and kind in REQUEST_INTENTS:  # B4 (#146)
        return Outcome.NEEDS_HUMAN, _request_text(state, packet.case_id), packet.case_id
    if packet is not None:
        locked = state.gate is GateResult.LOCKED_NOW
        outcome = Outcome.NOT_PERMITTED if locked else Outcome.NEEDS_HUMAN
        return outcome, _case_text(packet.case_id, locked), packet.case_id
    if kind in REQUEST_INTENTS and state.knowledge_answer is None:  # a guest's full surrender
        return Outcome.NOT_PERMITTED, LOGIN_FOR_REQUEST_TEXT, None
    if kind is IntentKind.THIRD_PARTY:
        if case.reason_for(state) is None:  # #82: no account bound, so no case
            return Outcome.NOT_PERMITTED, NO_ACCOUNT_THIRD_PARTY_TEXT, None
        return Outcome.UNAVAILABLE, UNAVAILABLE_TEXT, None  # the case was not opened
    if kind is IntentKind.OTHER_ACCOUNT:
        return Outcome.NOT_PERMITTED, OTHER_ACCOUNT_TEXT, None
    if kind is IntentKind.RESTRICTED_INFO:
        return Outcome.NOT_PERMITTED, RESTRICTED_TEXT, None
    gate = state.gate
    if kind in ACCOUNT_INTENTS and gate is not None:
        return _after_gate(state, gate)
    if kind in MONEY_INTENTS and gate is not None:
        return _gate_refusal(state, gate) or _after_money(state, money)
    # Issue #74 (found by /code-review on PR #72): the outcome follows what was asked. Since
    # ADR 0007 typed credentials never reach the gate, so no gate result leads into these replies.
    # B4 (#146): a guest's waiver or RMD question gets the documents' answer, with no case.
    if kind is IntentKind.PRODUCT_QUESTION or kind in REQUEST_INTENTS:
        answer = state.knowledge_answer
        if answer is None:
            return Outcome.UNAVAILABLE, UNAVAILABLE_TEXT, None
        if answer.found:
            return Outcome.ANSWERED, answer.text, None
        return Outcome.NO_SOURCE, answer.text, None
    if kind is IntentKind.OUT_OF_SCOPE:
        return Outcome.OUT_OF_SCOPE, OUT_OF_SCOPE_TEXT, None
    # Issue #177: a greeting or small talk (the Concierge's `other`) fell through to the refusal
    # below as NOT_PERMITTED, which PRD section 6 keeps for identity, status or tier blocks.
    # Nothing was asked, so it is answered with what the desk can do.
    if kind is IntentKind.OTHER:
        return Outcome.ANSWERED, HELLO_TEXT, None
    return Outcome.NOT_PERMITTED, NOT_YET_TEXT, None


def _gate_refusal(
    state: ConversationState, gate: GateResult
) -> tuple[Outcome, str, str | None] | None:
    """The gate's refusal for an account or money turn, or None when the gate let it through."""
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
    return None


def _after_money(state: ConversationState, money: MoneyFacts) -> tuple[Outcome, str, str | None]:
    """#88: a refused quote, a new quote, the yes, or what is still needed for one."""
    intent, proposal, yes = state.intent, state.proposal, state.confirmation
    if intent is None:  # _decide answers UNAVAILABLE first; kept for the type checker
        return Outcome.UNAVAILABLE, UNAVAILABLE_TEXT, None
    if money.refusal is not None:
        text = _refusal_text(money.refusal, intent.amount_cents, money.basis)
        return Outcome.NOT_PERMITTED, text, None
    if proposal is not None and proposal.quoted_turn == state.turn:
        return Outcome.ANSWERED, quote_text(proposal.quote, money.basis), None
    if proposal is not None and money.live:
        amount = proposal.quote.amount_cents
        if yes is not None and yes.proposal_id == proposal.proposal_id:
            if state.session.gate_b_passed:  # #89: confirmed and checked, waiting for a clear yes
                return Outcome.ANSWERED, _clear_yes_text(amount), None
            return Outcome.ANSWERED, STEP_UP_NEEDED_TEXT, None
        asks_without_amount = intent.kind is IntentKind.WITHDRAWAL and intent.amount_cents is None
        if not asks_without_amount:  # an answer to the live quote, but not a clear yes
            return Outcome.ANSWERED, _clear_yes_text(amount), None
    if intent.kind is IntentKind.WITHDRAWAL:
        return Outcome.ANSWERED, ASK_AMOUNT_TEXT, None
    return Outcome.NOT_PERMITTED, NOTHING_TO_CONFIRM_TEXT, None


def _after_gate(state: ConversationState, gate: GateResult) -> tuple[Outcome, str, str | None]:
    refused = _gate_refusal(state, gate)
    if refused is not None:
        return refused
    if state.account_view is not None:  # LOGGED_IN, PASSED or VERIFIED, and the account was read
        return Outcome.ANSWERED, _account_text(state.account_view), None
    return Outcome.UNAVAILABLE, UNAVAILABLE_TEXT, None  # passed, but the account was not read


def make(deps: Deps) -> NodeFn:
    def respond(state: ConversationState) -> dict[str, Any]:
        proposal = state.proposal
        live = is_live(deps.proposals, proposal)
        money = MoneyFacts(deps.turn.quote_refusal, deps.turn.quote_basis, live)
        outcome, text, reference = decide(state, deps.turn.failure, deps.turn.step_up, money)
        reply = Reply(text=text, outcome=outcome, reference=reference)
        answered = outcome in (Outcome.ANSWERED, Outcome.EXECUTED)  # #89: an execution answers
        citations = shown_citations(state, outcome)
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
