"""identity_gate (code): Gate A, the login, and the step-up check (ARCHITECTURE 3.2, ADR 0007).

No model is involved. A chat turn about the account is let through on a login and Gate A
(LOGGED_IN). The challenge runs only on a step-up turn: its values come from the step-up form,
which the runner put in the per-turn context, and go to `IdentityCheck.check_challenge` and nowhere
else. Credentials typed into chat are masked by the runner and never reach this node (ADR 0007).
The decision is written together with the session fields it depends on, in one update, because
the state checks the two against each other (issue #62).
"""

from typing import Any

from agents.nodes.common import Deps, NodeFn
from contracts.messages import ProposalStatus
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
        # Used at most once, then dropped on every path (review on PR #72).
        creds, deps.turn.credentials = deps.turn.credentials, None
        if s.customer_id is None:
            return {"gate": GateResult.NO_CUSTOMER}
        if not s.gate_a_trusted:  # GR-14: refuse, never ask
            audit(state, AuditEvent.GATE_A_REFUSED, s.failed_attempts)
            return {"gate": GateResult.UNTRUSTED}
        if s.locked:  # D-08: nothing unlocks a locked session, not even the right answer
            return {"gate": GateResult.LOCKED}
        if s.gate_b_passed:
            return {"gate": GateResult.VERIFIED}
        dob, last4 = (creds.dob, creds.last4) if creds is not None else (None, None)
        if not (deps.turn.step_up and s.authenticated and dob is not None and last4 is not None):
            # A chat turn: the login is enough for the account (ADR 0007). A session bound
            # without a login (DeskRunner.start, until contracts 0.7.0) gets ASK: log in first.
            return {"gate": GateResult.LOGGED_IN if s.authenticated else GateResult.ASK}

        deps.turn.record(Node.IDENTITY_GATE, Step.VERIFY_IDENTITY)
        if deps.identity.check_challenge(s.customer_id, dob, last4):
            audit(state, AuditEvent.GATE_B_PASSED, s.failed_attempts)
            return {"session.gate_b_passed": True, "gate": GateResult.PASSED}

        attempts = s.failed_attempts + 1
        audit(state, AuditEvent.GATE_B_FAILED, attempts)
        if attempts >= MAX_FAILED_CHALLENGES:
            audit(state, AuditEvent.LOCKED, attempts)
            # Review on PR #129: the lock left the confirmed proposal confirmed in the store.
            # Nothing in a locked session can pass the step-up, so it could never complete;
            # void it rather than leave a confirmed proposal for any later path to find (D-08).
            yes = state.confirmation
            if yes is not None and (
                deps.proposals.status(yes.proposal_id) is ProposalStatus.CONFIRMED
            ):
                deps.proposals.move(yes.proposal_id, ProposalStatus.VOIDED)
            return {
                "session.failed_attempts": attempts,
                "session.locked": True,
                "gate": GateResult.LOCKED_NOW,
            }
        return {"session.failed_attempts": attempts, "gate": GateResult.FAILED}

    return identity_gate
