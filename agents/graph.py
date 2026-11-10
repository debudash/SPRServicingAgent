"""The B2 graph (ARCHITECTURE 3.1, 3.2):

    intake -> concierge -> knowledge                                   -> respond
                        -> identity_gate -> (account | case | respond)  -> respond
                        -> case                                        -> respond
                        -> respond

Routing is code (ADR 0003): the model classifies, it never picks the next node. Every node's
writes pass through `contracts.state.check_write`; a node writing a field it does not own raises
ContractViolation and the runner fails the turn closed. Per-turn hop and time budgets are
enforced here; the tool budget is enforced where tools are called.
"""

import time
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from agents.nodes import account, case, concierge, identity_gate, intake, knowledge, respond
from agents.nodes.common import ACCOUNT_INTENTS, Deps, NodeFn, TurnContext
from contracts.messages import IntentKind
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
        # #82: a case names its customer (contracts 0.4.0), so with no account bound there is
        # nothing to open one for; respond refuses and points the owner to SPR.
        return Node.CASE.value if state.session.customer_id else Node.RESPOND.value
    if kind in (IntentKind.OTHER_ACCOUNT, IntentKind.RESTRICTED_INFO):  # NG-05, NG-08
        return Node.RESPOND.value
    # A complete set of credentials is a challenge attempt whatever the model called the turn:
    # routing is code (ADR 0003), so a mislabel cannot make the customer repeat them.
    creds = turn.credentials
    if kind in ACCOUNT_INTENTS or (creds is not None and creds.complete):
        return Node.IDENTITY_GATE.value
    if kind is IntentKind.PRODUCT_QUESTION:
        return Node.KNOWLEDGE.value
    return Node.RESPOND.value


def route_after_gate(state: ConversationState, turn: TurnContext) -> str:
    if turn.failure is not None:
        return Node.RESPOND.value
    if state.gate is GateResult.LOCKED_NOW:  # D-08: the third failure opens a case
        return Node.CASE.value
    kind = state.intent.kind if state.intent is not None else None
    # Issue #74 (found by /code-review on PR #72): every gated turn went to respond, so a
    # product question sent with credentials was never answered. The gate was visited because
    # credentials were present; a turn that is not about the account continues on its own route.
    if kind not in ACCOUNT_INTENTS:
        return Node.KNOWLEDGE.value if kind is IntentKind.PRODUCT_QUESTION else Node.RESPOND.value
    if state.gate in (GateResult.PASSED, GateResult.VERIFIED):
        return Node.ACCOUNT.value
    return Node.RESPOND.value


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
        (Node.RESPOND, respond),
    ):
        g.add_node(node.value, cast(Any, _guarded(node, module.make(deps), turn)))
    g.add_edge(START, Node.INTAKE.value)
    g.add_edge(Node.INTAKE.value, Node.CONCIERGE.value)
    g.add_conditional_edges(
        Node.CONCIERGE.value,
        lambda s: route_after_concierge(s, turn),
        [Node.KNOWLEDGE.value, Node.IDENTITY_GATE.value, Node.CASE.value, Node.RESPOND.value],
    )
    g.add_conditional_edges(
        Node.IDENTITY_GATE.value,
        lambda s: route_after_gate(s, turn),
        [Node.ACCOUNT.value, Node.CASE.value, Node.KNOWLEDGE.value, Node.RESPOND.value],
    )
    for node in (Node.KNOWLEDGE, Node.ACCOUNT, Node.CASE):
        g.add_edge(node.value, Node.RESPOND.value)
    g.add_edge(Node.RESPOND.value, END)
    return g.compile()
