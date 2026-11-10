"""identity_gate (code): Gate A, then the Gate B challenge (ARCHITECTURE 3.2, ADR 0005).

No model is involved. The candidates come from the per-turn context, where the runner put them
after masking the turn; they go to `IdentityCheck.check_challenge` and nowhere else. The decision is
written together with the session fields it depends on, in one update, because the state checks the
two against each other (issue #62).
"""

from typing import Any

from agents.nodes.common import Deps, NodeFn
from contracts.ports import AuditEvent
from contracts.state import MAX_FAILED_CHALLENGES, ConversationState, GateResult
from contracts.tools import Node, Step


def make(deps: Deps) -> NodeFn:
    def audit(state: ConversationState, event: AuditEvent, attempts: int) -> None:
        deps.audit.append(
            conversation_id=state.conversation_id,
            turn=state.turn,
            node=Node.IDENTITY_GATE,
            event=event,
            payload={"failed_attempts": attempts},  # a count only: never a candidate (FR-23)
            versions=state.versions.model_dump(mode="json"),
        )

    def identity_gate(state: ConversationState) -> dict[str, Any]:
        s = state.session
        if s.customer_id is None:
            return {"gate": GateResult.NO_CUSTOMER}
        if not s.gate_a_trusted:  # GR-14: refuse, never ask
            audit(state, AuditEvent.GATE_A_REFUSED, s.failed_attempts)
            return {"gate": GateResult.UNTRUSTED}
        if s.locked:  # D-08: nothing unlocks a locked session, not even the right answer
            return {"gate": GateResult.LOCKED}
        if s.gate_b_passed:
            return {"gate": GateResult.VERIFIED}

        creds, deps.turn.credentials = deps.turn.credentials, None  # used once, then dropped
        if creds is None or creds.dob is None or creds.last4 is None:
            return {"gate": GateResult.ASK}  # ADR 0005: nothing usable is not an attempt

        deps.turn.record(Node.IDENTITY_GATE, Step.VERIFY_IDENTITY)
        if deps.identity.check_challenge(s.customer_id, creds.dob, creds.last4):
            audit(state, AuditEvent.GATE_B_PASSED, s.failed_attempts)
            return {"session.gate_b_passed": True, "gate": GateResult.PASSED}

        attempts = s.failed_attempts + 1
        audit(state, AuditEvent.GATE_B_FAILED, attempts)
        if attempts >= MAX_FAILED_CHALLENGES:
            audit(state, AuditEvent.LOCKED, attempts)
            return {
                "session.failed_attempts": attempts,
                "session.locked": True,
                "gate": GateResult.LOCKED_NOW,
            }
        return {"session.failed_attempts": attempts, "gate": GateResult.FAILED}

    return identity_gate
