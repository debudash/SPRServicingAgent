"""execute (code): moves the money through the ledger, once (FR-08 to FR-10, ADR 0003, #89).

There is no execute tool: only this node, after the approval edge issued a token, calls
`Ledger.execute`. The ledger re-checks everything in one database transaction (the token, the
hash, the status, the kill switch) and writes the transaction and its audit row together. A replay
returns the first Execution (FR-09). A refusal ends the turn with nothing executed, and respond
claims execution only when an Execution exists (GR-10).
"""

import logging
from typing import Any

from agents.nodes.common import Deps, NodeFn
from contracts.state import ConversationState
from contracts.tools import Node, Step

logger = logging.getLogger(__name__)


def make(deps: Deps) -> NodeFn:
    def execute(state: ConversationState) -> dict[str, Any]:
        approval, money = state.approval, deps.money
        if approval is None or approval.token_hmac is None or money is None:
            return {}
        deps.turn.record(Node.EXECUTE, Step.EXECUTE)
        versions = state.versions.model_dump(mode="json")
        versions["documents"] = dict(deps.turn.policy_versions)  # FR-10: the policy in force
        try:
            done = money.ledger.execute(
                approval.proposal_id, approval.token_hmac, state.turn, versions
            )
        except Exception:  # ExecutionRefused, or the balance no longer covers it
            logger.exception("execution refused")
            deps.turn.failure = "execution_refused"
            return {}
        return {"execution": done}

    return execute
