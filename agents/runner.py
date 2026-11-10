"""GraphDeskRunner: implements `contracts.ports.LoginDeskRunner` over the desk graph.

Conversation state lives in memory for now (a persisted store arrives with later bullets). The
runner owns the turn counter, budgets, transcript and trace (FIELD_WRITERS).

ADR 0007: a customer session starts at `login`; `start(None)` is a guest. The step-up form's
values arrive through `step_up`, never as chat text: they travel only in the per-turn context, and
the transcript records that the form was submitted, never what it held.
"""

import logging
import re
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import date

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import ValidationError

from agents.graph import build_graph
from agents.guards.credentials import DOB_MASK, Credentials, capture
from agents.llm import chat_model, load_model_map
from agents.nodes.common import Deps, Stores, TurnContext
from agents.nodes.respond import NO_STEP_UP_TEXT, STEP_UP_INCOMPLETE_TEXT, UNAVAILABLE_TEXT
from agents.tools.registry import ToolRegistry
from contracts import CONTRACTS_VERSION
from contracts.outcomes import Outcome
from contracts.ports import AuditEvent, AuditLog, KnowledgeSearch, LoginRefused, TurnResult
from contracts.state import (
    Budgets,
    ContractViolation,
    ConversationState,
    Session,
    TraceEvent,
    TranscriptEntry,
    Versions,
    step_up_pending,
)
from contracts.tools import Node, Role, ToolName

logger = logging.getLogger(__name__)

_MODEL_ROLES = (Role.CONCIERGE, Role.KNOWLEDGE)
# What the transcript keeps of a step-up: that the form was used, never its values (ADR 0007).
STEP_UP_ENTRY = "[identity check submitted]"
_LAST4 = re.compile(r"\d{4}")


def _credential_in_play(state: ConversationState) -> bool:
    """Whether a bare four-digit group in this turn should be masked as possible SSN digits.

    Issue #114 (found by /code-review on PR #113): this was "bound, no step-up, not locked",
    which meant "a chat challenge is outstanding" before ADR 0007. With the login it held for
    every logged-in customer until the step-up, which comes after the quote, so "withdraw 5000"
    reached the model as "[SSN-4]". A credential is in play only while the step-up form is shown
    (the customer may type the answer into chat), or right after a turn that gave a date of birth
    (#67: the last four sent on its own next turn). Otherwise an amount stays an amount.
    """
    if step_up_pending(state):
        return True
    said = [e.text for e in state.transcript if e.role == "customer"]
    return bool(said) and DOB_MASK in said[-1]


def _fresh_turn(
    prior: ConversationState, turn_no: int, started: float, customer_text: str
) -> ConversationState:
    """A new turn's starting state: per-turn results cleared, the runner's own fields advanced,
    the customer's (masked) text appended. The one reset every turn uses, through the graph or
    refused before it.

    Review of PR #61: the gate decision, the account view and the case are this turn's, so one
    turn's decision never stands in for the next turn's check. Issue #115 (found by /code-review
    on PR #113): the refused step-up built its state by hand and skipped this reset.
    """
    return prior.model_copy(
        update={
            "turn": turn_no,
            "budgets": Budgets(
                turn_started_monotonic=started, cost_micros=prior.budgets.cost_micros
            ),
            "intent": None,
            "gate": None,
            "account_view": None,
            "case_packet": None,
            "knowledge_answer": None,
            "reply": None,
            "transcript": [
                *prior.transcript,
                TranscriptEntry(role="customer", turn=turn_no, text=customer_text),
            ],
        }
    )


class GraphDeskRunner:
    def __init__(
        self,
        search: KnowledgeSearch,
        audit: AuditLog,
        models: Mapping[Role, BaseChatModel] | None = None,
        clock: Callable[[], date] = date.today,
        *,
        stores: Stores,
    ) -> None:
        self._audit = audit
        self._stores = stores
        self._clock = clock
        spec = load_model_map()
        self._model_names = {role: spec[role].model for role in spec}
        self._models: dict[Role, BaseChatModel] = (
            dict(models) if models is not None else {r: chat_model(r) for r in _MODEL_ROLES}
        )
        self._registry = ToolRegistry()
        self._registry.register(ToolName.SEARCH_KB, search.search)
        self._states: dict[str, ConversationState] = {}
        self._turns_taken: dict[str, int] = {}

    def start(self, customer_id: str | None) -> str:
        """A guest session (None). A customer ID binds without a login, so account intents are
        told to log in; contracts 0.7.0 (#105) narrows `start` to guests."""
        return self._open(Session(customer_id=customer_id))

    def login(self, customer_id: str, password: str) -> str | LoginRefused:
        """The simulated upstream login (ADR 0007). A refusal opens nothing and says nothing about
        which part was wrong."""
        if not self._stores.passwords.check_password(customer_id, password):
            return LoginRefused()
        # Created bound and authenticated, as `start` creates it bound: intake owns these fields
        # during turns and re-reads Gate A from the account on every turn.
        return self._open(Session(customer_id=customer_id, authenticated=True))

    def _open(self, session: Session) -> str:
        conversation_id = f"conv-{uuid.uuid4().hex[:12]}"
        self._states[conversation_id] = ConversationState(
            conversation_id=conversation_id,
            as_of=self._clock(),
            session=session,
            versions=Versions(contracts=CONTRACTS_VERSION),
        )
        self._turns_taken[conversation_id] = 0
        return conversation_id

    def send(self, conversation_id: str, text: str) -> TurnResult:
        prior = self._prior(conversation_id)
        started = time.monotonic()
        # ADR 0005, narrowed by ADR 0007: mask credentials first, so the raw turn never enters the
        # state, the transcript, a model call or the trace. What is captured is discarded: typed
        # credentials are never checked (the step-up form is the only way in).
        text, _ = capture(text, prior.as_of, _credential_in_play(prior))
        return self._turn(prior, text, TurnContext(started=started))

    def step_up(self, conversation_id: str, dob: date, last4: str) -> TurnResult:
        """The step-up form (ADR 0007). With none pending it counts nothing (NOT_PERMITTED)."""
        prior = self._prior(conversation_id)
        ctx = TurnContext(started=time.monotonic())
        if not step_up_pending(prior):
            return self._refused_turn(prior, ctx, NO_STEP_UP_TEXT)
        # Issue #116 (found by /code-review on PR #113): any last4 went to the check, so an
        # empty or malformed value (a caller's bug, never a real answer) counted as a failed
        # attempt and could lock the customer out. Nothing usable is not an attempt (ADR 0005).
        if not _LAST4.fullmatch(last4):
            return self._refused_turn(prior, ctx, STEP_UP_INCOMPLETE_TEXT)
        ctx.step_up = True
        ctx.credentials = Credentials(dob=dob, last4=last4)
        return self._turn(prior, STEP_UP_ENTRY, ctx)

    def _prior(self, conversation_id: str) -> ConversationState:
        if conversation_id not in self._states:
            raise KeyError(f"unknown conversation {conversation_id}")
        return self._states[conversation_id]

    def _next_turn(self, conversation_id: str) -> int:
        turn_no = self._turns_taken[conversation_id] + 1
        self._turns_taken[conversation_id] = turn_no
        return turn_no

    def _turn(self, prior: ConversationState, text: str, ctx: TurnContext) -> TurnResult:
        """Run one turn through the graph. `text` is already masked, or the step-up marker."""
        conversation_id = prior.conversation_id
        turn_no = self._next_turn(conversation_id)
        started = ctx.started
        deps = Deps(
            audit=self._audit,
            registry=self._registry,
            models=self._models,
            model_names=self._model_names,
            clock=self._clock,
            turn=ctx,
            accounts=self._stores.accounts,
            identity=self._stores.identity,
            cases=self._stores.cases,
        )
        state = _fresh_turn(prior, turn_no, started, text)

        outcome_state: ConversationState | None = None
        try:
            result = build_graph(deps).invoke(state)
            outcome_state = ConversationState.model_validate(result)
            reply = outcome_state.reply
            if reply is None:
                raise ContractViolation("the turn ended without a reply")
            outcome, reply_text, reference = reply.outcome, reply.text, reply.reference
        except (ContractViolation, ValidationError):
            # Review of PR #61: a state the contracts refuse (say, an account view without both
            # gates) is a contract violation, not a provider error, so the eval does not mark it na.
            logger.exception("turn failed closed on a contract violation")
            outcome, reply_text, reference = Outcome.UNAVAILABLE, UNAVAILABLE_TEXT, None
            self._audit_fallback(state, ctx)
        except Exception:
            logger.exception("turn failed closed")
            ctx.provider_error = True
            outcome, reply_text, reference = Outcome.UNAVAILABLE, UNAVAILABLE_TEXT, None
            self._audit_fallback(state, ctx)

        final = outcome_state or state
        citations = (
            final.knowledge_answer.citations
            if outcome is Outcome.ANSWERED and final.knowledge_answer is not None
            else ()
        )
        trace = list(final.trace)
        for node in ctx.nodes:
            trace.append(TraceEvent(turn=turn_no, node=node))
        for node, step in zip(ctx.step_nodes, ctx.steps, strict=True):
            trace.append(TraceEvent(turn=turn_no, node=node, step=step))
        self._states[conversation_id] = final.model_copy(
            update={
                "turn": turn_no,
                "budgets": Budgets(
                    hops=ctx.hops,
                    tool_calls=ctx.tool_calls,
                    turn_started_monotonic=started,
                    cost_micros=final.budgets.cost_micros,
                ),
                "trace": trace,
                "transcript": [
                    *state.transcript,
                    TranscriptEntry(role="desk", turn=turn_no, text=reply_text),
                ],
            }
        )
        return TurnResult(
            conversation_id=conversation_id,
            turn=turn_no,
            reply_text=reply_text,
            outcome=outcome,
            reference=reference,
            citations=tuple(citations),
            steps=tuple(ctx.steps),
            nodes=tuple(ctx.nodes),
            usage=ctx.usage(),
            latency_ms=int((time.monotonic() - started) * 1000),
            provider_error=ctx.provider_error,
            step_up_required=step_up_pending(self._states[conversation_id]),
        )

    def _refused_turn(self, prior: ConversationState, ctx: TurnContext, text: str) -> TurnResult:
        """A turn refused before the graph (a step-up with nothing pending): it counts nothing,
        still writes its one audit row, and keeps the transcript honest about what happened."""
        conversation_id = prior.conversation_id
        turn_no = self._next_turn(conversation_id)
        state = _fresh_turn(prior, turn_no, ctx.started, STEP_UP_ENTRY)  # issue #115
        self._audit.append(
            conversation_id=conversation_id,
            turn=turn_no,
            node=Node.RUNNER,
            event=AuditEvent.REFUSED,
            payload={"outcome": Outcome.NOT_PERMITTED.value, "steps": []},
            versions=state.versions.model_dump(mode="json"),
        )
        self._states[conversation_id] = state.model_copy(
            update={
                "transcript": [
                    *state.transcript,
                    TranscriptEntry(role="desk", turn=turn_no, text=text),
                ]
            }
        )
        return TurnResult(
            conversation_id=conversation_id,
            turn=turn_no,
            reply_text=text,
            outcome=Outcome.NOT_PERMITTED,
            latency_ms=int((time.monotonic() - ctx.started) * 1000),
            step_up_required=step_up_pending(self._states[conversation_id]),
        )

    def _audit_fallback(self, state: ConversationState, ctx: TurnContext) -> None:
        """A turn that failed before respond still writes its one audit row."""
        if ctx.audited:
            return
        self._audit.append(
            conversation_id=state.conversation_id,
            turn=state.turn,
            node=Node.RUNNER,
            event=AuditEvent.REFUSED,
            payload={"outcome": Outcome.UNAVAILABLE.value, "steps": [s.value for s in ctx.steps]},
            versions=state.versions.model_dump(mode="json"),
        )
        ctx.audited = True
