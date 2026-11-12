"""The desk graph (ARCHITECTURE 3.1, 3.2, ADR 0007):

    intake -> concierge -> knowledge                                   -> respond
                        -> identity_gate -> (account | case | respond)  -> respond
                        -> identity_gate -> transaction -> confirm      -> respond   (#88)
                        -> identity_gate -> confirm                     -> respond   (#88)
                        -> case                                        -> respond
                        -> respond
    intake -> identity_gate -> (case | respond)        a step-up turn (the form, no chat text)

    #89, once a confirmed proposal's step-up has passed (on the step-up turn, or on a later yes):
    ... -> rules -> compliance -> approval -> execute    -> respond   (approve: one execution)
                                          -> case       -> respond   (hold, escalate, any flag)
    A human-tier quote the customer asks to go ahead with goes from confirm to case (GR-19).

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
    approval,
    case,
    compliance,
    concierge,
    confirm,
    execute,
    identity_gate,
    intake,
    knowledge,
    respond,
    rules,
    transaction,
)
from agents.nodes.common import (
    ACCOUNT_INTENTS,
    MONEY_INTENTS,
    REQUEST_INTENTS,
    Deps,
    NodeFn,
    TurnContext,
    is_live,
)
from contracts.messages import CaseReason, Decision, IntentKind, ProposalStatus
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
    if kind in REQUEST_INTENTS:  # B4 (#146): the documents answer, then a person decides
        if kind is IntentKind.FULL_SURRENDER:  # NG-07: nothing to look up, a person decides
            return Node.CASE.value if case.reason_for(state) else Node.RESPOND.value
        return Node.KNOWLEDGE.value
    # ADR 0007: credentials typed into chat are masked and never checked, so only what was asked
    # decides the route.
    if kind in ACCOUNT_INTENTS or kind in MONEY_INTENTS:  # #88: a quote needs the login too
        return Node.IDENTITY_GATE.value
    if kind is IntentKind.PRODUCT_QUESTION:
        return Node.KNOWLEDGE.value
    return Node.RESPOND.value


def route_after_knowledge(state: ConversationState, turn: TurnContext) -> str:
    """B4 (#146): a waiver or RMD request opens a case after the documents' answer (FR-13,
    FR-15), when a customer is logged in. Product questions end with the answer."""
    if turn.failure is not None or state.intent is None:
        return Node.RESPOND.value
    if state.intent.kind in REQUEST_INTENTS and case.reason_for(state) is not None:
        return Node.CASE.value
    return Node.RESPOND.value


def route_money(state: ConversationState, proposals: ProposalStore) -> str:
    """#88: a stated amount that is not the live quote's is a new quote (BH-B3-02: a changed amount
    is never a yes). Anything else is an answer to the live quote, which confirm judges."""
    intent, proposal = state.intent, state.proposal
    amount = intent.amount_cents if intent is not None else None
    live = proposal is not None and is_live(proposals, proposal)
    # Issue #140 (found by the money-path red team, #90): any stated amount with no live quote was
    # quoted, so "yes, go ahead with $5,000" repeated after that withdrawal executed became a new
    # quote, and a bare yes then executed a second one. A yes answers a quote: it replaces only a
    # live quote for another amount (BH-B3-02). With none live it quotes nothing, and respond says
    # no quote is waiting. A new withdrawal is asked for as one.
    if intent is not None and intent.kind is IntentKind.CONFIRM and not live:
        return Node.CONFIRM.value
    if amount is not None and (
        proposal is None or not live or amount != proposal.quote.amount_cents
    ):
        return Node.TRANSACTION.value
    # Issue #189: "how much can I withdraw?" went to confirm, which reads no account, so the reply
    # could only ask for an amount. A withdrawal with no amount and no quote waiting reads the
    # account view, and respond states the allowance and balance before asking how much.
    asks = intent is not None and intent.kind is IntentKind.WITHDRAWAL and amount is None
    if asks and not live:
        return Node.ACCOUNT.value
    return Node.CONFIRM.value


def ready_for_review(state: ConversationState, proposals: ProposalStore) -> bool:
    """#89: the proposal is confirmed in the store, the yes is for it, and the step-up has passed
    this session. Only then does it go to the rules, Compliance and the ledger (FR-08)."""
    yes, proposal = state.confirmation, state.proposal
    return (
        yes is not None
        and proposal is not None
        and yes.proposal_id == proposal.proposal_id
        and state.session.gate_b_passed
        and proposals.status(proposal.proposal_id) is ProposalStatus.CONFIRMED
    )


def route_after_confirm(
    state: ConversationState, turn: TurnContext, proposals: ProposalStore
) -> str:
    """#89: a yes in a session that already passed the step-up goes straight on; a go-ahead on a
    human-tier quote goes to a person (GR-19). Anything else is answered."""
    if turn.failure is not None:
        return Node.RESPOND.value
    intent = state.intent
    if intent is not None and intent.explicit_yes and ready_for_review(state, proposals):
        return Node.RULES.value
    if case.reason_for(state) is CaseReason.WITHDRAWAL_REVIEW:
        return Node.CASE.value
    return Node.RESPOND.value


def route_after_rules(state: ConversationState, turn: TurnContext, can_review: bool) -> str:
    """Issue #137 (found by /code-review on PR #135): a flagged proposal went straight to a case,
    but FR-11 has Compliance review every proposal (it cannot approve a flagged one), and the
    reviewer's packet needs its reasons (BH-B4-01). So every proposal goes to Compliance; the
    flags make its approve impossible. Only with no policy source wired (no money path) does a
    flagged proposal go straight to a person."""
    if turn.failure is not None or state.rule_flags is None:
        return Node.RESPOND.value
    if state.rule_flags.flags and not can_review:
        return Node.CASE.value
    return Node.COMPLIANCE.value


def route_after_compliance(state: ConversationState, turn: TurnContext) -> str:
    if turn.failure is not None or state.compliance is None:
        return Node.RESPOND.value
    return Node.APPROVAL.value


def route_after_approval(state: ConversationState, turn: TurnContext) -> str:
    if turn.failure is not None or state.approval is None:
        return Node.RESPOND.value
    if state.approval.decision is Decision.APPROVE:
        return Node.EXECUTE.value
    return Node.CASE.value  # hold or escalate: a person decides (FR-12, ARCHITECTURE 3.4)


def route_after_gate(state: ConversationState, turn: TurnContext, proposals: ProposalStore) -> str:
    if turn.failure is not None:
        return Node.RESPOND.value
    if state.gate is GateResult.LOCKED_NOW:  # D-08: the third failure opens a case
        return Node.CASE.value
    if turn.step_up:  # #89: a pass continues the confirmed withdrawal; anything else is the reply
        passed = state.gate is GateResult.PASSED and ready_for_review(state, proposals)
        return Node.RULES.value if passed else Node.RESPOND.value
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
        (Node.RULES, rules),
        (Node.COMPLIANCE, compliance),
        (Node.APPROVAL, approval),
        (Node.EXECUTE, execute),
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
            Node.RULES.value,
            Node.RESPOND.value,
        ],
    )
    # #88: every quote passes confirm, which drops a yes given to the quote it replaced.
    g.add_edge(Node.TRANSACTION.value, Node.CONFIRM.value)
    g.add_conditional_edges(
        Node.CONFIRM.value,
        lambda s: route_after_confirm(s, turn, deps.proposals),
        [Node.RULES.value, Node.CASE.value, Node.RESPOND.value],
    )
    g.add_conditional_edges(
        Node.RULES.value,
        lambda s: route_after_rules(s, turn, deps.money is not None),
        [Node.CASE.value, Node.COMPLIANCE.value, Node.RESPOND.value],
    )
    g.add_conditional_edges(
        Node.COMPLIANCE.value,
        lambda s: route_after_compliance(s, turn),
        [Node.APPROVAL.value, Node.RESPOND.value],
    )
    g.add_conditional_edges(
        Node.APPROVAL.value,
        lambda s: route_after_approval(s, turn),
        [Node.EXECUTE.value, Node.CASE.value, Node.RESPOND.value],
    )
    g.add_conditional_edges(
        Node.KNOWLEDGE.value,
        lambda s: route_after_knowledge(s, turn),
        [Node.CASE.value, Node.RESPOND.value],
    )
    for node in (Node.ACCOUNT, Node.CASE, Node.EXECUTE):
        g.add_edge(node.value, Node.RESPOND.value)
    g.add_edge(Node.RESPOND.value, END)
    return g.compile()
