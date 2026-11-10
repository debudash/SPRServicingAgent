"""intake: sets up the turn. Writes the versions in force and the session binding.

The customer ID is bound when the conversation starts (auth is upstream). `intake` records Gate A
for it from the account store each turn (issue #59); Gate B belongs to identity_gate.
"""

from typing import Any

from agents.nodes.common import Deps, NodeFn
from agents.prompts import load
from contracts import CONTRACTS_VERSION
from contracts.state import ConversationState, Versions
from contracts.tools import Role

PROMPT_IDS = {Role.CONCIERGE: "concierge", Role.KNOWLEDGE: "knowledge"}


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
            "versions": Versions(
                contracts=CONTRACTS_VERSION,
                models=models,
                prompts=prompts,
            ),
        }

    return intake
