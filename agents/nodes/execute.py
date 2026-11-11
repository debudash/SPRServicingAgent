"""execute (code): moves the money through the ledger, once (FR-08 to FR-10, ADR 0003, #89).

There is no execute tool: only this node, after the approval edge issued a token, calls
`Ledger.execute`. The ledger re-checks everything in one database transaction (the token, the
hash, the status, the kill switch) and writes the transaction and its audit row together. A replay
returns the first Execution (FR-09). A refusal ends the turn with nothing executed, and respond
claims execution only when an Execution exists (GR-10).
"""

import logging
import re
from collections.abc import Iterable
from typing import Any

from agents.nodes.common import Deps, NodeFn
from contracts.messages import ComplianceDecision, ProposalStatus, Reason
from contracts.ports import ExecutionRefused
from contracts.state import ConversationState
from contracts.tools import Node, Step

_REF = re.compile(r"^(?P<doc_id>\S+) v(?P<version>\d+) §")


def cited_versions(review: ComplianceDecision | None) -> dict[str, int]:
    """FR-10: the policy versions Compliance cited, read from its decision's references."""
    return versions_cited(review.reasons if review else ())


def versions_cited(reasons: Iterable[Reason]) -> dict[str, int]:
    """FR-10: the policy versions a set of reasons cites (Compliance's, or a case packet's)."""
    versions: dict[str, int] = {}
    for reason in reasons:
        m = _REF.match(reason.policy_ref)
        if m:
            versions[m["doc_id"]] = int(m["version"])
    return versions


logger = logging.getLogger(__name__)


def make(deps: Deps) -> NodeFn:
    def execute(state: ConversationState) -> dict[str, Any]:
        approval, money = state.approval, deps.money
        if approval is None or approval.token_hmac is None or money is None:
            return {}
        deps.turn.record(Node.EXECUTE, Step.EXECUTE)
        versions = state.versions.model_dump(mode="json")
        versions["documents"] = cited_versions(state.compliance)  # FR-10: the policy in force
        try:
            done = money.ledger.execute(
                approval.proposal_id, approval.token_hmac, state.turn, versions
            )
        except (ExecutionRefused, ValueError):  # the ledger refused, or the balance moved
            # Review on PR #135: a refused approval stayed approved with an unused token. Nothing
            # moved; send it to a person rather than leave it approved (GR-18, GR-21).
            logger.exception("execution refused")
            if deps.proposals.status(approval.proposal_id) is ProposalStatus.APPROVED:
                deps.proposals.move(approval.proposal_id, ProposalStatus.ESCALATED)
            deps.turn.failure = "execution_refused"
            return {}
        return {"execution": done}

    return execute
