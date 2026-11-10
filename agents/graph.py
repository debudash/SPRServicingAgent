"""The desk graph (ARCHITECTURE 3.1, 3.2, ADR 0007):

    intake -> concierge -> knowledge                                   -> respond
                        -> identity_gate -> (account | case | respond)  -> respond
                        -> identity_gate -> transaction -> confirm      -> respond   (#88)
                        -> identity_gate -> confirm                     -> respond   (#88)
                        -> case                                        -> respond
                        -> respond
    intake -> identity_gate -> (case | respond)        a step-up turn (the form, no chat text)

Routing is code (ADR 0003): the model classifies, it never picks the next node. Every node's
writes pass through `contracts.state.check_write`; a node writing a field it does not own raises
ContractViolation and the runner fails the turn closed. Per-turn hop and time budgets are
enforced here; the tool budget is enforced where tools are called.
"""

import time
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from agents.nodes import (
    account,
    case,
    concierge,
    confirm,
    identity_gate,
    intake,
    knowledge,
    respond,
    transaction,
)
from agents.nodes.common import (
    ACCOUNT_INTENTS,
    MONEY_INTENTS,
    Deps,
    NodeFn,
    TurnContext,
    is_live,
)
from contracts.messages import IntentKind
from contracts.ports import ProposalStore
from contracts.state import (
    MAX_HOPS_PER_TURN,
    MAX_SECONDS_PER_TURN,
    ConversationState,
    GateResult,
    Session,
    check_write,
)
from contracts.tools import Node


def apply_writes(node: Node, state: ConversationState, updates: dict[str, Any]) -> dict[str, Any]:
    """Check each written field against its owner; fold `session.<field>` into one Session."""
    out: dict[str, Any] = {}
    session_changes: dict[str, Any] = {}
    for field, value in updates.items():
        check_write(node, field)
        if field.startswith("session."):
            session_changes[field.removeprefix("session.")] = value
        else:
            out[field] = value
    if session_changes:
        out["session"] = Session.model_validate({**state.session.model_dump(), **session_changes})
    return out


def _guarded(node: Node, fn: NodeFn, turn: TurnContext) -> NodeFn:
    def run(state: ConversationState) -> dict[str, Any]:
        if node is not Node.RESPOND:  # respond always runs: it writes the turn's one audit row
            if turn.failure is not None:
                return {}
            turn.hops += 1
            if (
                turn.hops > MAX_HOPS_PER_TURN
                or time.monotonic() - turn.started > MAX_SECONDS_PER_TURN
            ):
                turn.failure = "budget"
                return {}
        turn.nodes.append(node)
        return apply_writes(node, state, fn(state))

    return run


def route_after_concierge(state: ConversationState, turn: TurnContext) -> str:
    if turn.failure is not None or state.intent is None:
        return Node.RESPOND.value
    kind = state.intent.kind
    if kind is IntentKind.THIRD_PARTY:  # D-09: a case, before any identity question
        # #82: no account bound means no case (case.reason_for); respond points to SPR.
        return Node.CASE.value if case.reason_for(state) else Node.RESPOND.value
    if kind in (IntentKind.OTHER_ACCOUNT, IntentKind.RESTRICTED_INFO):  # NG-05, NG-08
        return Node.RESPOND.value
    # ADR 0007: credentials typed into chat are masked and never checked, so only what was asked
    # decides the route.
    if kind in ACCOUNT_INTENTS or kind in MONEY_INTENTS:  # #88: a quote needs the login too
        return Node.IDENTITY_GATE.value
    if kind is IntentKind.PRODUCT_QUESTION:
        return Node.KNOWLEDGE.value
    return Node.RESPOND.value


def route_money(state: ConversationState, proposals: ProposalStore) -> str:
    """#88: a stated amount that is not the live quote's is a new quote (BH-B3-02: a changed amount
    is never a yes). Anything else is an answer to the live quote, which confirm judges."""
    intent, proposal = state.intent, state.proposal
    amount = intent.amount_cents if intent is not None else None
    if amount is not None and (
        proposal is None
        or not is_live(proposals, proposal)
        or amount != proposal.quote.amount_cents
    ):
        return Node.TRANSACTION.value
    return Node.CONFIRM.value


def route_after_gate(state: ConversationState, turn: TurnContext, proposals: ProposalStore) -> str:
    if turn.failure is not None:
        return Node.RESPOND.value
    if state.gate is GateResult.LOCKED_NOW:  # D-08: the third failure opens a case
        return Node.CASE.value
    if turn.step_up:  # the step-up's result is the reply; #88/#89 continue the withdrawal
        return Node.RESPOND.value
    kind = state.intent.kind if state.intent is not None else None
    # Issue #74 (found by /code-review on PR #72): a turn that is not about the account continues
    # on its own route. Since ADR 0007 only account intents reach the gate, so this is a guard.
    if kind not in ACCOUNT_INTENTS and kind not in MONEY_INTENTS:
        return Node.KNOWLEDGE.value if kind is IntentKind.PRODUCT_QUESTION else Node.RESPOND.value
    if state.gate not in (GateResult.LOGGED_IN, GateResult.PASSED, GateResult.VERIFIED):
        return Node.RESPOND.value
    if kind in MONEY_INTENTS:
        return route_money(state, proposals)
    return Node.ACCOUNT.value


def route_after_intake(state: ConversationState, turn: TurnContext) -> str:
    """A step-up turn has no chat text for the Concierge: it goes straight to the gate."""
    if turn.failure is None and turn.step_up:
        return Node.IDENTITY_GATE.value
    return Node.CONCIERGE.value


def build_graph(deps: Deps) -> Any:
    turn = deps.turn
    g = StateGraph(ConversationState)
    for node, module in (
        (Node.INTAKE, intake),
        (Node.CONCIERGE, concierge),
        (Node.KNOWLEDGE, knowledge),
        (Node.IDENTITY_GATE, identity_gate),
        (Node.ACCOUNT, account),
        (Node.CASE, case),
        (Node.TRANSACTION, transaction),
        (Node.CONFIRM, confirm),
        (Node.RESPOND, respond),
    ):
        g.add_node(node.value, cast(Any, _guarded(node, module.make(deps), turn)))
    g.add_edge(START, Node.INTAKE.value)
    g.add_conditional_edges(
        Node.INTAKE.value,
        lambda s: route_after_intake(s, turn),
        [Node.CONCIERGE.value, Node.IDENTITY_GATE.value],
    )
    g.add_conditional_edges(
        Node.CONCIERGE.value,
        lambda s: route_after_concierge(s, turn),
        [Node.KNOWLEDGE.value, Node.IDENTITY_GATE.value, Node.CASE.value, Node.RESPOND.value],
    )
    g.add_conditional_edges(
        Node.IDENTITY_GATE.value,
        lambda s: route_after_gate(s, turn, deps.proposals),
        [
            Node.ACCOUNT.value,
            Node.CASE.value,
            Node.KNOWLEDGE.value,
            Node.TRANSACTION.value,
            Node.CONFIRM.value,
            Node.RESPOND.value,
        ],
    )
    # #88: every quote passes confirm, which drops a yes given to the quote it replaced.
    g.add_edge(Node.TRANSACTION.value, Node.CONFIRM.value)
    for node in (Node.KNOWLEDGE, Node.ACCOUNT, Node.CASE, Node.CONFIRM):
        g.add_edge(node.value, Node.RESPOND.value)
    g.add_edge(Node.RESPOND.value, END)
    return g.compile()
