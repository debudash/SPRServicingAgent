"""Chat UI with a fake runner (no network, no model)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agents.wiring import MissingApiKeyError, require_api_key
from contracts.messages import Citation
from contracts.outcomes import Outcome
from contracts.ports import TurnResult, Usage
from contracts.tools import Node

APP = str(Path(__file__).parents[1] / "ui" / "app.py")


class FakeRunner:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.started: list[str | None] = []

    def start(self, customer_id: str | None) -> str:
        self.started.append(customer_id)
        return f"conv-{len(self.started)}"

    def send(self, conversation_id: str, text: str) -> TurnResult:
        self.sent.append((conversation_id, text))
        return TurnResult(
            conversation_id=conversation_id,
            turn=1,
            reply_text="The year 5 surrender charge is 3%.",
            outcome=Outcome.ANSWERED,
            citations=(Citation(doc_id="fee_schedule", version=1, section="Year 5"),),
            nodes=(Node.CONCIERGE, Node.KNOWLEDGE),
            usage=Usage(cost_micros=12_500),
        )


def test_message_shows_reply_and_outcome() -> None:
    runner = FakeRunner()
    at = AppTest.from_file(APP)
    at.session_state["runner"] = runner
    at.run()
    at.chat_input[0].set_value("What is the surrender charge?").run()
    assert not at.exception
    assert runner.sent == [("conv-1", "What is the surrender charge?")]
    assert any("surrender charge is 3%" in m.value for m in at.markdown)
    sidebar_text = " ".join(m.value for m in at.sidebar.markdown)
    assert Outcome.ANSWERED.value in sidebar_text
    assert "$0.0125" in sidebar_text
    assert "fee_schedule v1" in sidebar_text


def test_missing_api_key_shows_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = AppTest.from_file(APP)
    at.run()
    assert not at.exception
    assert any("ANTHROPIC_API_KEY" in e.value for e in at.error)


def test_require_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingApiKeyError):
        require_api_key()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    require_api_key()


# ---------- #59: "signed in as" stands in for upstream auth ----------
def test_signing_in_starts_a_conversation_bound_to_that_customer() -> None:
    runner = FakeRunner()
    at = AppTest.from_file(APP)
    at.session_state["runner"] = runner
    at.run()
    assert runner.started == [None]  # anonymous until a customer is picked
    at.sidebar.selectbox(key="signed_in_as").select("SPR-1001").run()
    assert not at.exception
    assert runner.started == [None, "SPR-1001"]
    at.chat_input[0].set_value("What's my balance?").run()
    assert runner.sent == [("conv-2", "What's my balance?")]
