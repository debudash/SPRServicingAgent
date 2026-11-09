import re
from typing import Any, cast

from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from agents.llm import build_messages, chat_model, load_model_map
from agents.testing import ScriptedChatModel
from contracts.tools import Role

SYSTEM = "You are the Concierge. Be brief."


def test_map_covers_every_role() -> None:
    m = load_model_map()
    assert set(m) == set(Role)
    assert m[Role.COMPLIANCE].effort == "high"
    assert m[Role.CASE].model == "claude-haiku-5-5"
    assert m[Role.TRANSACTION].effort == "medium"


def test_chat_model_builds_without_network(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-real")
    llm = chat_model(Role.KNOWLEDGE)
    assert llm.model == "claude-sonnet-5-5"
    assert llm.reasoning_effort == "medium"
    assert llm.temperature is None


def test_system_prompt_stable_across_conversations() -> None:
    a = build_messages(SYSTEM, "ctx A", [HumanMessage("hi")])
    b = build_messages(SYSTEM, "ctx B", [HumanMessage("other"), AIMessage("x")])
    assert a[0] == b[0]
    assert a[0].model_dump_json() == b[0].model_dump_json()
    assert [type(x) for x in a[:2]] == [type(a[0]), HumanMessage]
    assert a[2].content == "hi"
    blocks = cast(list[dict[str, Any]], a[0].content)
    block = blocks[0]
    assert block["cache_control"] == {"type": "ephemeral"}
    assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}|thread|conversation", str(block["text"]))


def test_scripted_returns_in_order_and_records() -> None:
    class Out(BaseModel):
        n: int

    fake = ScriptedChatModel(["one", AIMessage("two"), Out(n=3)])
    assert fake.invoke("q1").content == "one"
    assert fake.invoke("q2").content == "two"
    assert fake.with_structured_output(Out).invoke("q3") == Out(n=3)
    assert len(fake.calls) == 3
    assert fake.calls[0][0].content == "q1"
