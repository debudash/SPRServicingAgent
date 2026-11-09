"""intake: sets up the turn. Writes the versions in force and the session binding.

Credentials and identity (Gate A, Gate B, scrubbing) belong to B2 and are not here: `intake`
binds only the customer ID the conversation was started with, and Gate A stays untrusted.
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
        return {
            "as_of": deps.clock(),
            "versions": Versions(
                contracts=CONTRACTS_VERSION,
                models=models,
                prompts=prompts,
            ),
        }

    return intake
