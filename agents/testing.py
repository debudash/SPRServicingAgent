"""Test doubles. Tests use only these: no network, no API key."""

from collections import deque
from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import PrivateAttr


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
