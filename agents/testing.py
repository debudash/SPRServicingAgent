"""Test doubles. Tests use only these: no network, no API key."""

from collections import deque
from collections.abc import Sequence
from datetime import date
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import PrivateAttr

from contracts.messages import AccountView, CasePacket, Confirmation


class ScriptedChatModel(BaseChatModel):
    """Returns queued responses in order and records every call's messages.

    A queued str or AIMessage answers plain calls; any other object (a pydantic
    model, dict) is returned as-is by `with_structured_output(...)` calls.
    """

    _queue: deque[Any] = PrivateAttr(default_factory=deque)
    _calls: list[list[BaseMessage]] = PrivateAttr(default_factory=list)

    def __init__(self, responses: Sequence[Any] = (), **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._queue.extend(responses)

    @property
    def calls(self) -> list[list[BaseMessage]]:
        return self._calls

    def queue(self, *responses: Any) -> None:
        self._queue.extend(responses)

    def _next(self, messages: list[BaseMessage]) -> Any:
        self._calls.append(list(messages))
        if not self._queue:
            raise AssertionError("ScriptedChatModel: no queued response left")
        return self._queue.popleft()

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        item = self._next(messages)
        msg = item if isinstance(item, AIMessage) else AIMessage(content=str(item))
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable[Any, Any]:
        return self

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable[Any, Any]:
        def run(prompt: Any) -> Any:
            return self._next(self._to_messages(prompt))

        return RunnableLambda(run)

    @staticmethod
    def _to_messages(prompt: Any) -> list[BaseMessage]:
        return prompt if isinstance(prompt, list) else [prompt]


# ---------- B2 ports (issue #59): in-memory stand-ins for the data lane's stores ----------
class MemoryAccounts:
    """`AccountStore` over fixed views. `trusted` is Gate A; `views` are returned as stored."""

    def __init__(self, views: dict[str, AccountView], trusted: set[str]) -> None:
        self.views = views
        self.trusted = trusted
        self.viewed: list[str] = []

    def gate_a(self, customer_id: str) -> bool:
        return customer_id in self.trusted

    def view(self, customer_id: str, as_of: date) -> AccountView:
        self.viewed.append(customer_id)
        return self.views[customer_id]


class MemoryIdentity:
    """`IdentityCheck` over fixed (dob, last4) pairs. Records only how often it was called."""

    def __init__(self, stored: dict[str, tuple[date, str]]) -> None:
        self._stored = stored
        self.checks = 0

    def check_challenge(self, customer_id: str, dob: date, last4: str) -> bool:
        self.checks += 1
        return self._stored.get(customer_id) == (dob, last4)


class MemoryCases:
    """`CaseStore` that keeps every packet it was given."""

    def __init__(self) -> None:
        self.opened: list[CasePacket] = []

    def open(self, packet: CasePacket) -> None:
        if any(p.case_id == packet.case_id for p in self.opened):
            raise ValueError(f"duplicate case {packet.case_id}")
        self.opened.append(packet)


class MemoryPasswords:
    """`PasswordCheck` over fixed passwords (ADR 0007). Records only how often it was called."""

    def __init__(self, passwords: dict[str, str]) -> None:
        self._passwords = passwords
        self.checks = 0

    def check_password(self, customer_id: str, password: str) -> bool:
        self.checks += 1
        return bool(password) and self._passwords.get(customer_id) == password


def put_pending_confirmation(runner: Any, conversation_id: str) -> None:
    """Stand in for the confirm node (#88): the customer has said yes to a quote, so a step-up
    is pending (`contracts.state.step_up_pending`). Test-only: it writes the runner's state
    directly."""
    state = runner._states[conversation_id]
    runner._states[conversation_id] = state.model_copy(
        update={
            "confirmation": Confirmation(
                proposal_id="P-TEST", amount_cents=345_600, turn=max(state.turn, 1) + 1
            )
        }
    )
