"""The B1 graph: intake -> concierge -> (knowledge | respond) -> respond.

Routing is code (ADR 0003): the model classifies, it never picks the next node. Every node's
writes pass through `contracts.state.check_write`; a node writing a field it does not own raises
ContractViolation and the runner fails the turn closed. Per-turn hop and time budgets are
enforced here; the tool budget is enforced where tools are called.
"""

import time
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from agents.nodes import concierge, intake, knowledge, respond
from agents.nodes.common import Deps, NodeFn, TurnContext
from contracts.messages import IntentKind
from contracts.state import (
    MAX_HOPS_PER_TURN,
    MAX_SECONDS_PER_TURN,
    ConversationState,
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
    if turn.failure is None and state.intent is not None:
        if state.intent.kind is IntentKind.PRODUCT_QUESTION:
            return Node.KNOWLEDGE.value
    return Node.RESPOND.value


def build_graph(deps: Deps) -> Any:
    turn = deps.turn
    g = StateGraph(ConversationState)
    for node, module in (
        (Node.INTAKE, intake),
        (Node.CONCIERGE, concierge),
        (Node.KNOWLEDGE, knowledge),
        (Node.RESPOND, respond),
    ):
        g.add_node(node.value, cast(Any, _guarded(node, module.make(deps), turn)))
    g.add_edge(START, Node.INTAKE.value)
    g.add_edge(Node.INTAKE.value, Node.CONCIERGE.value)
    g.add_conditional_edges(
        Node.CONCIERGE.value,
        lambda s: route_after_concierge(s, turn),
        [Node.KNOWLEDGE.value, Node.RESPOND.value],
    )
    g.add_edge(Node.KNOWLEDGE.value, Node.RESPOND.value)
    g.add_edge(Node.RESPOND.value, END)
    return g.compile()
