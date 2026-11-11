"""intake: sets up the turn. Writes the versions in force and the session binding.

The customer ID is bound when the conversation starts (auth is upstream). `intake` records Gate A
for it from the account store each turn (issue #59); Gate B belongs to identity_gate.
"""

from typing import Any

from agents.nodes.common import Deps, NodeFn
from agents.prompts import load
from contracts import CONTRACTS_VERSION
from contracts.state import ConversationState, Switches, Versions
from contracts.tools import Role

PROMPT_IDS = {
    Role.CONCIERGE: "concierge",
    Role.KNOWLEDGE: "knowledge",
    Role.COMPLIANCE: "compliance",
}


def make(deps: Deps) -> NodeFn:
    def intake(state: ConversationState) -> dict[str, Any]:
        prompts = {pid: str(load(pid)[1]) for pid in PROMPT_IDS.values()}
        models = {
            role.value: deps.model_names[role] for role in PROMPT_IDS if role in deps.model_names
        }
        customer_id = state.session.customer_id
        trusted = customer_id is not None and deps.accounts.gate_a(customer_id)
        return {
            "session.gate_a_trusted": trusted,
            "as_of": deps.clock(),
            # FR-26: no money path means nothing can execute, so the switch reads off.
            "switches": Switches(
                execution_enabled=bool(deps.money and deps.money.execution_enabled)
            ),
            "versions": Versions(
                contracts=CONTRACTS_VERSION,
                models=models,
                prompts=prompts,
            ),
        }

    return intake
