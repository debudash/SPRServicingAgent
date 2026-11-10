"""GraphDeskRunner: implements `contracts.ports.DeskRunner` over the desk graph.

Conversation state lives in memory for now (a persisted store arrives with later bullets). The
runner owns the turn counter, budgets, transcript and trace (FIELD_WRITERS).
"""

import logging
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import date

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import ValidationError

from agents.graph import build_graph
from agents.guards.credentials import capture
from agents.llm import chat_model, load_model_map
from agents.nodes.common import Deps, Stores, TurnContext
from agents.nodes.respond import UNAVAILABLE_TEXT
from agents.tools.registry import ToolRegistry
from contracts import CONTRACTS_VERSION
from contracts.outcomes import Outcome
from contracts.ports import AuditEvent, AuditLog, KnowledgeSearch, TurnResult
from contracts.state import (
    Budgets,
    ContractViolation,
    ConversationState,
    Session,
    TraceEvent,
    TranscriptEntry,
    Versions,
)
from contracts.tools import Node, Role, ToolName

logger = logging.getLogger(__name__)

_MODEL_ROLES = (Role.CONCIERGE, Role.KNOWLEDGE)


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
        conversation_id = f"conv-{uuid.uuid4().hex[:12]}"
        self._states[conversation_id] = ConversationState(
            conversation_id=conversation_id,
            as_of=self._clock(),
            session=Session(customer_id=customer_id),
            versions=Versions(contracts=CONTRACTS_VERSION),
        )
        self._turns_taken[conversation_id] = 0
        return conversation_id

    def send(self, conversation_id: str, text: str) -> TurnResult:
        if conversation_id not in self._states:
            raise KeyError(f"unknown conversation {conversation_id}")
        prior = self._states[conversation_id]
        turn_no = self._turns_taken[conversation_id] + 1
        self._turns_taken[conversation_id] = turn_no
        started = time.monotonic()
        # ADR 0005: capture credentials first, so the raw turn never enters the state, the
        # transcript, a model call or the trace. Only the masked text moves on.
        s = prior.session
        challenge_open = s.customer_id is not None and not s.gate_b_passed and not s.locked
        text, credentials = capture(text, prior.as_of, challenge_open)

        ctx = TurnContext(started=started, credentials=credentials)
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
        # A fresh turn: per-turn results cleared, the runner's own fields advanced.
        state = prior.model_copy(
            update={
                "turn": turn_no,
                "budgets": Budgets(
                    turn_started_monotonic=started, cost_micros=prior.budgets.cost_micros
                ),
                # Review of PR #61: the gate decision, the account view and the case are this
                # turn's, so one turn's decision never stands in for the next turn's check.
                "intent": None,
                "gate": None,
                "account_view": None,
                "case_packet": None,
                "knowledge_answer": None,
                "reply": None,
                "transcript": [
                    *prior.transcript,
                    TranscriptEntry(role="customer", turn=turn_no, text=text),
                ],
            }
        )

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
