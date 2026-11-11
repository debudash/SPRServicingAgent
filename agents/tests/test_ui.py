"""Chat UI with a fake runner (no network, no model): login page, chat, step-up form (ADR 0007)."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agents.wiring import MissingApiKeyError, require_api_key
from contracts.messages import (
    CasePacket,
    CaseReason,
    CaseStatus,
    CaseSummary,
    Citation,
    Decision,
    HumanDecision,
    Quote,
    ReviewResult,
    RuleFlag,
    ThresholdTier,
)
from contracts.outcomes import Outcome
from contracts.ports import LoginRefused, TurnResult, Usage
from contracts.tools import Node

APP = str(Path(__file__).parents[1] / "ui" / "app.py")


class FakeRunner:
    def __init__(self, step_up_required: bool = False) -> None:
        self.sent: list[tuple[str, str]] = []
        self.started: list[str | None] = []
        self.logins: list[str] = []
        self.step_ups: list[tuple[str, date, str]] = []
        self.step_up_required = step_up_required

    def start(self, customer_id: str | None) -> str:
        self.started.append(customer_id)
        return f"guest-{len(self.started)}"

    def login(self, customer_id: str, password: str) -> str | LoginRefused:
        if password != "right":
            return LoginRefused()
        self.logins.append(customer_id)
        return f"conv-{customer_id}"

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
            step_up_required=self.step_up_required,
        )

    def step_up(self, conversation_id: str, dob: date, last4: str) -> TurnResult:
        self.step_ups.append((conversation_id, dob, last4))
        return TurnResult(
            conversation_id=conversation_id,
            turn=2,
            reply_text="Thank you, that's confirmed.",
            outcome=Outcome.ANSWERED,
        )


def _app(runner: FakeRunner) -> AppTest:
    at = AppTest.from_file(APP)
    at.session_state["runner"] = runner
    at.run()
    return at


def _log_in(at: AppTest, customer: str, password: str) -> None:
    at.selectbox(key="login_customer").select(customer)
    at.text_input(key="login_password").input(password)
    at.button(key="login_submit").click().run()


def test_the_desk_opens_on_the_login_page() -> None:
    runner = FakeRunner()
    at = _app(runner)
    assert not at.exception
    # Each demo customer is shown with their name; the value behind it is the ID.
    assert at.selectbox(key="login_customer").options == [
        "SPR-1001 · Margaret Holloway",
        "SPR-1002 · Raymond Okafor",
        "SPR-1003 · Linda Chu",
        "SPR-1004 · Thomas Brennan",
    ]
    assert (
        at.text_input(key="login_password").proto.type
        == at.text_input(key="login_password").proto.PASSWORD
    )  # masked
    assert len(at.chat_input) == 0  # no chat before a login or the guest link
    assert runner.started == [] and runner.logins == []


def test_a_wrong_password_shows_an_error_and_no_chat() -> None:
    runner = FakeRunner()
    at = _app(runner)
    _log_in(at, "SPR-1001", "wrong")
    assert not at.exception
    assert any("don't match" in e.value for e in at.error)
    assert len(at.chat_input) == 0 and runner.logins == []


def test_a_login_opens_the_chat_for_that_customer() -> None:
    runner = FakeRunner()
    at = _app(runner)
    _log_in(at, "SPR-1001", "right")
    assert runner.logins == ["SPR-1001"]
    at.chat_input[0].set_value("What's my balance?").run()
    assert not at.exception
    assert runner.sent == [("conv-SPR-1001", "What's my balance?")]
    assert "SPR-1001" in " ".join(m.value for m in at.sidebar.markdown)


def test_message_shows_reply_and_outcome_for_a_guest() -> None:
    runner = FakeRunner()
    at = _app(runner)
    at.button(key="guest").click().run()
    assert runner.started == [None]
    at.chat_input[0].set_value("What is the surrender charge?").run()
    assert not at.exception
    assert runner.sent == [("guest-1", "What is the surrender charge?")]
    assert any("surrender charge is 3%" in m.value for m in at.markdown)
    sidebar_text = " ".join(m.value for m in at.sidebar.markdown)
    assert Outcome.ANSWERED.value in sidebar_text
    assert "$0.0125" in sidebar_text
    assert "fee_schedule v1" in sidebar_text


def test_the_step_up_form_appears_when_asked_and_its_values_go_to_step_up_only() -> None:
    runner = FakeRunner(step_up_required=True)
    at = _app(runner)
    _log_in(at, "SPR-1001", "right")
    at.chat_input[0].set_value("Yes, go ahead").run()
    assert (
        at.text_input(key="step_up_last4").proto.type
        == at.text_input(key="step_up_last4").proto.PASSWORD
    )
    at.date_input(key="step_up_dob").set_value(date(1958, 3, 14))
    at.text_input(key="step_up_last4").input("7823")
    at.button(key="step_up_submit").click().run()
    assert not at.exception
    assert runner.step_ups == [("conv-SPR-1001", date(1958, 3, 14), "7823")]
    assert all("7823" not in text for _, text in runner.sent)  # never sent as chat
    shown = " ".join(m.value for m in at.markdown)
    assert "7823" not in shown and "1958" not in shown
    assert "that's confirmed" in shown


def test_no_step_up_form_unless_asked() -> None:
    runner = FakeRunner()
    at = _app(runner)
    _log_in(at, "SPR-1001", "right")
    at.chat_input[0].set_value("What's my balance?").run()
    assert not any(t.key == "step_up_last4" for t in at.text_input)


def test_log_out_returns_to_the_login_page() -> None:
    runner = FakeRunner()
    at = _app(runner)
    _log_in(at, "SPR-1001", "right")
    at.sidebar.button(key="logout").click().run()
    assert not at.exception
    assert len(at.chat_input) == 0
    assert at.selectbox(key="login_customer") is not None


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


# ---------- B4: the review queue (#146) ----------
class FakeReview:
    """A ReviewDesk with one open withdrawal review."""

    def __init__(self) -> None:
        self.decisions: list[HumanDecision] = []
        self.status = CaseStatus.OPEN

    def _row(self) -> CaseSummary:
        return CaseSummary(
            case_id="CASE-1",
            customer_id="SPR-1004",
            opened_for=CaseReason.WITHDRAWAL_REVIEW,
            status=self.status,
            opened_at=datetime(2026, 11, 10, tzinfo=UTC),
            proposal_id="prop-1",
            decided_by="human:pat" if self.decisions else None,
        )

    def queue(
        self, status: CaseStatus | None = None, customer_id: str | None = None
    ) -> list[CaseSummary]:
        row = self._row()
        if customer_id is not None and customer_id != row.customer_id:
            return []
        return [row] if status in (None, row.status) else []

    def case(self, case_id: str) -> CasePacket | None:
        return CasePacket(
            case_id="CASE-1",
            conversation_id="CV1",
            customer_id="SPR-1004",
            opened_for=CaseReason.WITHDRAWAL_REVIEW,
            request_summary="A withdrawal needs a person's review.",
            quote=QUOTE,
            rule_flags=frozenset({RuleFlag.OVER_AMOUNT}),
            excerpt="I want to withdraw $30,000.",
            recommendation="Review the proposal and its quote, then approve or reject it.",
            proposal_id="prop-1",
        )

    def decide(self, decision: HumanDecision) -> ReviewResult:
        self.decisions.append(decision)
        self.status = CaseStatus.APPROVED
        return ReviewResult(
            case_id="CASE-1",
            decision=decision.decision,
            outcome=Outcome.EXECUTED,
            reference="TX-1",
            text="Approved by pat and executed. Confirmation TX-1.",
        )


QUOTE = Quote(
    amount_cents=3_000_000,
    free_cents=2_100_000,
    excess_cents=900_000,
    rate_bp=300,
    charge_cents=27_000,
    net_cents=2_973_000,
    contract_year=5,
    threshold_tier=ThresholdTier.HUMAN,
    irs_notice=False,
)


def _review_app(review: FakeReview) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["runner"] = FakeRunner()
    at.session_state["review"] = review
    at.run()
    return at


def test_staff_open_the_review_queue_and_see_the_packet() -> None:
    at = _review_app(FakeReview())
    at.button(key="open_review").click().run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown)
    assert "Review queue" in " ".join(h.value for h in at.subheader)
    assert "over_amount" in page and "I want to withdraw $30,000." in page
    assert at.table  # the quote's figures


def test_a_reviewer_approves_from_the_queue() -> None:
    review = FakeReview()
    at = _review_app(review)
    at.button(key="open_review").click().run()
    at.text_input(key="reviewer_id").input("pat").run()
    at.button(key="approve-CASE-1").click().run()
    assert not at.exception
    assert [(d.reviewer_id, d.decision) for d in review.decisions] == [("pat", Decision.APPROVE)]
    assert any("TX-1" in s.value for s in at.success)


def test_the_customer_sees_their_cases() -> None:  # FR-18
    at = _review_app(FakeReview())
    _log_in(at, "SPR-1004", "right")
    assert not at.exception
    assert any("CASE-1" in m.value for m in at.sidebar.markdown) or any(
        "CASE-1" in str(t.value) for t in at.sidebar.text
    )
