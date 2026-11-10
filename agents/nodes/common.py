"""What nodes share: the per-turn context, injected dependencies and structured model calls."""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel

from agents.guards.credentials import Credentials
from agents.tools.registry import ToolRegistry
from contracts.messages import IntentKind
from contracts.ports import AccountStore, AuditLog, CaseStore, IdentityCheck, PasswordCheck, Usage
from contracts.state import MAX_TOOL_CALLS_PER_TURN, ConversationState
from contracts.tools import Node, Role, Step

NodeFn = Callable[[ConversationState], dict[str, Any]]

# Intents answered from the account, so a login and Gate A must hold first (FR-02, ADR 0007).
# Routing and respond share this one set.
ACCOUNT_INTENTS = frozenset({IntentKind.ACCOUNT_INFO, IntentKind.VERIFY})


class BudgetExceeded(Exception):
    """A per-turn hard stop (D-10): the turn ends with UNAVAILABLE and no action."""


@dataclass
class TurnContext:
    """Mutable bookkeeping for one turn. Owned by the runner; nodes only report into it."""

    started: float = field(default_factory=time.monotonic)
    hops: int = 0
    tool_calls: int = 0
    nodes: list[Node] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    # The node each step was taken in, for the trace (issue #59: B1 had one step-taking node).
    step_nodes: list[Node] = field(default_factory=list)
    failure: str | None = None  # set when the turn must end UNAVAILABLE
    provider_error: bool = False
    audited: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # The step-up form's values (ADR 0007), set only by the runner's `step_up`. Held here, outside
    # ConversationState, so they never reach a checkpoint or trace; read only by identity_gate.
    credentials: Credentials | None = field(default=None, repr=False)
    # This turn is the step-up form, not a chat message: it skips the Concierge (no text to read).
    step_up: bool = False

    def record(self, node: Node, step: Step) -> None:
        self.steps.append(step)
        self.step_nodes.append(node)

    def spend_tool_call(self) -> None:
        if self.tool_calls >= MAX_TOOL_CALLS_PER_TURN:
            raise BudgetExceeded("tool call budget used up")
        self.tool_calls += 1

    def usage(self) -> Usage:
        return Usage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens,
        )


@dataclass(frozen=True)
class Stores:
    """The records the desk reads and writes: accounts (Gate A, views), the identity check (the
    step-up), cases and the login's passwords. Built together by the wiring, passed together to
    the runner."""

    accounts: AccountStore
    identity: IdentityCheck
    cases: CaseStore
    passwords: PasswordCheck


@dataclass
class Deps:
    audit: AuditLog
    registry: ToolRegistry
    models: Mapping[Role, BaseChatModel]
    model_names: Mapping[Role, str]
    clock: Callable[[], date]
    turn: TurnContext
    accounts: AccountStore
    identity: IdentityCheck
    cases: CaseStore


def invoke_structured[T: BaseModel](
    model: BaseChatModel, schema: type[T], messages: list[Any], turn: TurnContext
) -> T:
    """One model call returning `schema`; token usage is added to the turn."""
    out: Any = model.with_structured_output(schema, include_raw=True).invoke(messages)
    if isinstance(out, dict) and "parsed" in out:
        raw = out.get("raw")
        meta = getattr(raw, "usage_metadata", None) or {}
        details = meta.get("input_token_details") or {}
        turn.input_tokens += int(meta.get("input_tokens", 0))
        turn.output_tokens += int(meta.get("output_tokens", 0))
        turn.cache_read_tokens += int(details.get("cache_read", 0))
        turn.cache_write_tokens += int(details.get("cache_creation", 0))
        if out.get("parsed") is None:
            raise ValueError("model output did not match the schema")
        out = out["parsed"]
    if isinstance(out, schema):
        return out
    return schema.model_validate(out)


def latest_customer_text(state: ConversationState) -> str:
    for entry in reversed(state.transcript):
        if entry.role == "customer":
            return entry.text
    return ""


def session_context(state: ConversationState) -> str:
    """Session facts safe for a model and stable across conversations: no IDs, no dates."""
    s = state.session
    if s.customer_id is None:
        who = "guest, not logged in"
    elif not s.authenticated:
        who = "bound to a customer who has not logged in"
    elif s.locked:
        who = "logged in; identity checks locked"
    elif s.gate_b_passed:
        who = "logged in; step-up check passed"
    else:
        who = "logged in"
    return f"Session: {who}. Customer turn {state.turn}."


def narrow(value: object) -> Any:
    return cast(Any, value)
