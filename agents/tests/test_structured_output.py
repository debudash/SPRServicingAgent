"""invoke_structured asks for the API's native structured output (issue #182)."""

from typing import Any

import pytest
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from agents.nodes.common import TurnContext, invoke_structured


class Draft(BaseModel):
    decision: str


class StrictModel:
    """Like Claude Sonnet 5.5 at high effort: a forced tool call is refused (HTTP 400)."""

    def __init__(self) -> None:
        self.methods: list[str | None] = []

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable[Any, Any]:
        self.methods.append(kwargs.get("method"))
        if kwargs.get("method") != "json_schema":
            raise ValueError('tool_choice: type "tool" and "any" are not supported for this model')
        return RunnableLambda(lambda _: {"raw": None, "parsed": schema(decision="escalate")})


def test_issue_182_structured_calls_use_json_schema_not_a_forced_tool() -> None:
    """#182, found by the owner in the local desk: every live Compliance call failed with a 400."""
    model = StrictModel()
    draft = invoke_structured(model, Draft, [], TurnContext())  # type: ignore[arg-type]
    assert draft == Draft(decision="escalate")
    assert model.methods == ["json_schema"]


def test_a_reply_that_does_not_match_the_schema_still_fails() -> None:
    class Empty(StrictModel):
        def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable[Any, Any]:
            return RunnableLambda(lambda _: {"raw": None, "parsed": None})

    with pytest.raises(ValueError, match="did not match"):
        invoke_structured(Empty(), Draft, [], TurnContext())  # type: ignore[arg-type]
