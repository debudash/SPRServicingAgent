"""account (code): reads the model-safe account view for the bound customer (FR-02, GR-02).

Routing sends a turn here only after identity_gate passed; the state refuses a view without both
gates or for anyone but the bound customer, so a routing bug fails closed rather than leaking.
"""

from typing import Any

from agents.nodes.common import Deps, NodeFn
from contracts.state import ConversationState
from contracts.tools import Node, Step


def make(deps: Deps) -> NodeFn:
    def account(state: ConversationState) -> dict[str, Any]:
        customer_id = state.session.customer_id
        if customer_id is None:
            return {}
        deps.turn.record(Node.ACCOUNT, Step.GET_ACCOUNT)
        return {"account_view": deps.accounts.view(customer_id, state.as_of)}

    return account
