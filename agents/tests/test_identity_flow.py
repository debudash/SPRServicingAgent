"""Issue #59: the B2 tracer bullet end to end with scripted models and in-memory stores.

G-B2-01..06, BH-B2-01 and BH-B2-02 (evals/golden/), plus the review hand-offs from PR #61.
"""

import sqlite3
from datetime import date

import pytest

from agents.guards.credentials import Credentials
from agents.nodes import identity_gate
from agents.nodes.common import Deps, Stores, TurnContext
from agents.nodes.knowledge import KnowledgeDraft
from agents.runner import GraphDeskRunner
from agents.testing import MemoryAccounts, MemoryCases, MemoryIdentity, ScriptedChatModel
from agents.tools.registry import ToolRegistry
from contracts import CONTRACTS_VERSION
from contracts.messages import (
    AccountStatus,
    AccountView,
    AgeBand,
    CasePacket,
    CaseReason,
    Intent,
    IntentKind,
)
from contracts.outcomes import Outcome
from contracts.ports import AuditEvent, TurnResult
from contracts.state import ConversationState, GateResult, Session, TraceEvent, Versions
from contracts.tools import Node, Role, Step

from .test_graph import FEES, FakeSearch, MemoryAudit, cited

AS_OF = date(2024, 12, 1)
CONTACT = "1-800-555-0192"
VERIFY_TEXT = "My date of birth is 1958-03-14 and the last four of my SSN are 7823."


def _view(cid: str, balance: int, year: int, allowance: int) -> AccountView:
    return AccountView(
        customer_id=cid,
        account_status=AccountStatus.ACTIVE,
        contract_year=year,
        age_band=AgeBand.FROM_59_5_TO_79,
        balance_cents=balance,
        allowance_remaining_cents=allowance,
        withdrawals_this_year=0,
    )


VIEWS = {
    "SPR-1001": _view("SPR-1001", 8_745_062, 3, 874_506),
    "SPR-1002": _view("SPR-1002", 4_210_000, 2, 421_000),
    "SPR-1003": _view("SPR-1003", 1_120_000, 4, 112_000),
    "SPR-1004": _view("SPR-1004", 21_000_000, 5, 2_100_000),
}
STORED = {
    "SPR-1001": (date(1958, 3, 14), "7823"),
    "SPR-1003": (date(1965, 7, 4), "9910"),
    "SPR-1004": (date(1952, 5, 22), "3367"),
}


class Desk:
    def __init__(
        self,
        *kinds: IntentKind,
        views: dict[str, AccountView] | None = None,
        drafts: tuple[KnowledgeDraft, ...] = (),
        cases: MemoryCases | None = None,
    ) -> None:
        self.search = FakeSearch([FEES])
        self.concierge = ScriptedChatModel([Intent(kind=k) for k in kinds])
        self.audit = MemoryAudit()
        self.accounts = MemoryAccounts(views or VIEWS, trusted={"SPR-1001", "SPR-1003", "SPR-1004"})
        self.identity = MemoryIdentity(STORED)
        self.cases = cases or MemoryCases()
        self.runner = GraphDeskRunner(
            search=self.search,
            audit=self.audit,
            models={Role.CONCIERGE: self.concierge, Role.KNOWLEDGE: ScriptedChatModel(drafts)},
            clock=lambda: AS_OF,
            stores=Stores(accounts=self.accounts, identity=self.identity, cases=self.cases),
        )

    def talk(self, customer: str | None, *texts: str) -> list[TurnResult]:
        self.conv = self.runner.start(customer)
        return [self.runner.send(self.conv, t) for t in texts]

    def events(self) -> list[AuditEvent]:
        return [r.event for r in self.audit.rows]


# ---------- G-B2-01: untrusted account, never challenged (GR-14) ----------
def test_g_b2_01_untrusted_account_gets_the_contact_number_and_no_challenge() -> None:
    desk = Desk(IntentKind.ACCOUNT_INFO)
    [r] = desk.talk("SPR-1002", "What's my current balance?")
    assert r.outcome is Outcome.NOT_PERMITTED
    assert CONTACT in r.reply_text
    assert "date of birth" not in r.reply_text.lower() and "ssn" not in r.reply_text.lower()
    assert Step.VERIFY_IDENTITY not in r.steps and Step.GET_ACCOUNT not in r.steps
    assert "42,100" not in r.reply_text
    assert desk.identity.checks == 0 and desk.accounts.viewed == []
    assert AuditEvent.GATE_A_REFUSED in desk.events()
    assert desk.runner._states[desk.conv].session.gate_a_trusted is False


# ---------- G-B2-02: trusted, not verified yet: ask, do not count ----------
def test_g_b2_02_trusted_account_is_asked_to_verify() -> None:
    desk = Desk(IntentKind.ACCOUNT_INFO)
    [r] = desk.talk("SPR-1001", "What's my current balance?")
    assert r.outcome is Outcome.NOT_PERMITTED
    assert "date of birth" in r.reply_text.lower() and "last four" in r.reply_text.lower()
    assert Step.GET_ACCOUNT not in r.steps and "87,450.62" not in r.reply_text
    session = desk.runner._states[desk.conv].session
    assert session.gate_a_trusted and not session.gate_b_passed and session.failed_attempts == 0


# ---------- BH-B2-02: ask, then verify, then the balance ----------
def test_bh_b2_02_verification_then_balance() -> None:
    desk = Desk(IntentKind.ACCOUNT_INFO, IntentKind.VERIFY)
    first, second = desk.talk(
        "SPR-1001", "What's my balance?", "1958-03-14, and the last four are 7823."
    )
    assert first.outcome is Outcome.NOT_PERMITTED
    assert second.outcome is Outcome.ANSWERED
    assert second.steps == (Step.VERIFY_IDENTITY, Step.GET_ACCOUNT)
    assert "$87,450.62" in second.reply_text
    assert second.nodes == (
        Node.INTAKE,
        Node.CONCIERGE,
        Node.IDENTITY_GATE,
        Node.ACCOUNT,
        Node.RESPOND,
    )
    assert AuditEvent.GATE_B_PASSED in desk.events()
    trace = desk.runner._states[desk.conv].trace
    assert TraceEvent(turn=2, node=Node.IDENTITY_GATE, step=Step.VERIFY_IDENTITY) in trace
    assert TraceEvent(turn=2, node=Node.ACCOUNT, step=Step.GET_ACCOUNT) in trace


# ---------- G-B2-03: verified on an earlier turn ----------
def test_g_b2_03_verified_customer_gets_the_balance_without_a_new_check() -> None:
    desk = Desk(IntentKind.VERIFY, IntentKind.ACCOUNT_INFO)
    _, r = desk.talk("SPR-1001", VERIFY_TEXT, "What's my current balance?")
    assert r.outcome is Outcome.ANSWERED
    assert r.steps == (Step.GET_ACCOUNT,)
    assert "87,450.62" in r.reply_text
    assert desk.identity.checks == 1


# ---------- G-B2-04: the owner asking for their own restricted fields (NG-08) ----------
def test_g_b2_04_restricted_fields_are_never_read_back() -> None:
    desk = Desk(IntentKind.VERIFY, IntentKind.RESTRICTED_INFO)
    _, r = desk.talk(
        "SPR-1001",
        VERIFY_TEXT,
        "Can you read me back the SSN and date of birth you have on file for me?",
    )
    assert r.outcome is Outcome.NOT_PERMITTED
    for leaked in ("7823", "1958-03-14", "03/14/1958"):
        assert leaked not in r.reply_text
    assert Step.GET_ACCOUNT not in r.steps


# ---------- G-B2-05: another customer's account (NG-05) ----------
def test_g_b2_05_another_account_gets_nothing() -> None:
    desk = Desk(IntentKind.VERIFY, IntentKind.OTHER_ACCOUNT)
    _, r = desk.talk(
        "SPR-1001", VERIFY_TEXT, "Also, what's the balance on account SPR-1004? It's my brother's."
    )
    assert r.outcome is Outcome.NOT_PERMITTED
    assert "210,000" not in r.reply_text
    assert "SPR-1004" not in desk.accounts.viewed


# ---------- G-B2-06: a third party gets a case, never the account (D-09) ----------
def test_g_b2_06_third_party_opens_a_case() -> None:
    desk = Desk(IntentKind.THIRD_PARTY)
    [r] = desk.talk(
        "SPR-1003",
        "I'm Linda's son and I handle her finances. What's her balance and can I take some out?",
    )
    assert r.outcome is Outcome.NEEDS_HUMAN
    assert r.steps == (Step.CREATE_CASE,)
    assert Step.GET_ACCOUNT not in r.steps and Step.QUOTE not in r.steps
    assert "11,200" not in r.reply_text
    [packet] = desk.cases.opened
    assert packet.opened_for is CaseReason.THIRD_PARTY and packet.customer_id == "SPR-1003"
    assert r.reference == packet.case_id and packet.case_id in r.reply_text
    assert desk.accounts.viewed == []
    case_rows = [row for row in desk.audit.rows if row.event is AuditEvent.CASE_OPENED]
    assert [row.case_id for row in case_rows] == [packet.case_id]


# ---------- BH-B2-01: three failures lock the session and open a case (D-08) ----------
def test_bh_b2_01_three_failures_lock_and_the_right_answer_no_longer_unlocks() -> None:
    desk = Desk(
        IntentKind.ACCOUNT_INFO,
        IntentKind.VERIFY,
        IntentKind.VERIFY,
        IntentKind.VERIFY,
        IntentKind.ACCOUNT_INFO,
    )
    turns = desk.talk(
        "SPR-1001",
        "What's my balance?",
        "My date of birth is 1960-01-01 and my last four are 1111.",
        "Sorry, 1958-03-15 and 7832.",
        "OK, 1958-03-14 and 0000.",
        "Fine: 1958-03-14 and 7823. Now what's my balance?",
    )
    assert [t.outcome for t in turns] == [Outcome.NOT_PERMITTED] * 5
    assert desk.identity.checks == 3  # the locked fifth turn is never checked
    locking = turns[3]
    assert Step.CREATE_CASE in locking.steps
    [packet] = desk.cases.opened
    assert packet.opened_for is CaseReason.LOCKED and locking.reference == packet.case_id
    assert all("87,450.62" not in t.reply_text for t in turns)
    assert Step.GET_ACCOUNT not in turns[4].steps
    events = desk.events()
    assert events.count(AuditEvent.GATE_B_FAILED) == 3
    assert AuditEvent.LOCKED in events and AuditEvent.CASE_OPENED in events
    for digits in ("7823", "7832", "1111", "1958", "1960"):
        assert digits not in packet.model_dump_json()
    assert desk.runner._states[desk.conv].session.locked


def test_a_failed_attempt_says_so_and_is_counted() -> None:
    desk = Desk(IntentKind.VERIFY)
    [r] = desk.talk("SPR-1001", "1958-03-15 and 7832")
    assert r.outcome is Outcome.NOT_PERMITTED and r.steps == (Step.VERIFY_IDENTITY,)
    assert desk.runner._states[desk.conv].session.failed_attempts == 1


# ---------- ADR 0005: no usable candidates asks again and is not counted ----------
def test_partial_credentials_ask_again_uncounted() -> None:
    desk = Desk(IntentKind.VERIFY)
    [r] = desk.talk("SPR-1001", "My date of birth is 1958-03-14.")
    assert r.outcome is Outcome.NOT_PERMITTED
    assert "last four" in r.reply_text.lower()
    assert desk.identity.checks == 0
    assert desk.runner._states[desk.conv].session.failed_attempts == 0


def test_complete_credentials_are_checked_whatever_the_model_called_the_turn() -> None:
    # Routing is code (ADR 0003): a full set of candidates goes to the gate even if the
    # Concierge mislabels the turn, so the customer is not asked again for what they just gave.
    desk = Desk(IntentKind.OTHER)
    [r] = desk.talk("SPR-1001", "1958-03-14 7823")
    assert desk.identity.checks == 1 and r.steps[0] is Step.VERIFY_IDENTITY


def test_anonymous_session_is_not_challenged() -> None:
    desk = Desk(IntentKind.ACCOUNT_INFO)
    [r] = desk.talk(None, "What's my balance?")
    assert r.outcome is Outcome.NOT_PERMITTED
    assert "date of birth" not in r.reply_text.lower()
    assert desk.identity.checks == 0


# ---------- hand-offs from the review of PR #61 ----------
def test_gate_and_account_view_do_not_outlive_their_turn() -> None:
    desk = Desk(IntentKind.VERIFY, IntentKind.OUT_OF_SCOPE)
    first, _ = desk.talk("SPR-1001", VERIFY_TEXT, "Should I buy bitcoin instead?")
    assert first.outcome is Outcome.ANSWERED
    state = desk.runner._states[desk.conv]
    assert state.gate is None and state.account_view is None and state.case_packet is None
    assert state.session.gate_b_passed  # the session, unlike the per-turn fields, persists


def test_gate_result_is_recorded_with_its_session() -> None:
    desk = Desk(IntentKind.VERIFY)
    desk.talk("SPR-1001", VERIFY_TEXT)
    state = desk.runner._states[desk.conv]
    assert state.gate is GateResult.PASSED and state.session.gate_b_passed


def test_a_state_validation_error_fails_closed_as_a_contract_violation() -> None:
    # A store bug that hands back another customer's view must not reach the customer: the
    # state refuses it (NG-05) and the turn ends UNAVAILABLE, not as a provider error.
    desk = Desk(IntentKind.VERIFY, views={**VIEWS, "SPR-1001": VIEWS["SPR-1004"]})
    [r] = desk.talk("SPR-1001", VERIFY_TEXT)
    assert r.outcome is Outcome.UNAVAILABLE
    assert not r.provider_error
    assert "210,000" not in r.reply_text


# ---------- #73: the lockout was lost when opening the lock case failed ----------
# Found by /code-review on PR #72 (spec). D-08, GR-21: the lock holds if the case store fails.
class BrokenCases(MemoryCases):
    def open(self, packet: CasePacket) -> None:
        raise sqlite3.OperationalError("database is locked")


def test_issue_73_lock_holds_when_the_case_store_fails() -> None:
    desk = Desk(*[IntentKind.VERIFY] * 4, cases=BrokenCases())
    turns = desk.talk(
        "SPR-1001",
        "1960-01-01 and 1111",
        "1958-03-15 and 7832",
        "1958-03-14 and 0000",
        VERIFY_TEXT,
    )
    session = desk.runner._states[desk.conv].session
    assert session.locked and session.failed_attempts == 3
    assert desk.identity.checks == 3  # the right answer after the lock is never checked
    locking = turns[2]
    assert not locking.provider_error
    assert locking.outcome is Outcome.NOT_PERMITTED
    assert CONTACT in locking.reply_text and "case" in locking.reply_text.lower()
    assert turns[3].outcome is Outcome.NOT_PERMITTED and "87,450.62" not in turns[3].reply_text


# ---------- #74: credentials in a turn swallowed the customer's actual request ----------
# Found by /code-review on PR #72 (spec). GR-20: the outcome is about what the customer asked.
MIXED = "DOB 1958-03-14, last four of SSN 7823. Is the year 5 surrender charge 4%?"


def test_issue_74_credentials_with_a_product_question_get_the_answer() -> None:
    desk = Desk(IntentKind.PRODUCT_QUESTION, drafts=(cited(FEES, "Year 5 is 3%."),))
    [r] = desk.talk("SPR-1001", MIXED)
    assert desk.identity.checks == 1  # the credentials were still checked
    assert r.steps == (Step.VERIFY_IDENTITY, Step.SEARCH_KB)
    assert r.outcome is Outcome.ANSWERED and "3%" in r.reply_text
    assert desk.runner._states[desk.conv].session.gate_b_passed


def test_issue_74_anonymous_credentials_with_a_product_question_get_the_answer() -> None:
    desk = Desk(IntentKind.PRODUCT_QUESTION, drafts=(cited(FEES, "Year 5 is 3%."),))
    [r] = desk.talk(None, MIXED)
    assert r.outcome is Outcome.ANSWERED and "3%" in r.reply_text
    assert "sign in" not in r.reply_text.lower()
    assert desk.identity.checks == 0


@pytest.mark.parametrize("verified_first", [False, True])
def test_issue_74_credentials_with_an_unbuilt_request_are_never_answered(
    verified_first: bool,
) -> None:
    kinds = [IntentKind.VERIFY] * verified_first + [IntentKind.WITHDRAWAL]
    desk = Desk(*kinds)
    texts = [VERIFY_TEXT] * verified_first + ["1958-03-14 and 7823, withdraw $2,000 please"]
    r = desk.talk("SPR-1001", *texts)[-1]
    assert r.outcome is Outcome.NOT_PERMITTED
    assert "yet" in r.reply_text


def test_issue_74_a_failed_challenge_is_still_reported_on_a_product_turn() -> None:
    desk = Desk(IntentKind.PRODUCT_QUESTION, drafts=(cited(FEES, "Year 5 is 3%."),))
    [r] = desk.talk("SPR-1001", "DOB 1958-03-15, SSN last four 7832. Is year 5 4%?")
    assert desk.runner._states[desk.conv].session.failed_attempts == 1
    assert "don't match" in r.reply_text and "3%" in r.reply_text


# ---------- review follow-ups on PR #72 ----------
def test_the_lock_case_excerpt_covers_the_conversation_masked() -> None:
    desk = Desk(*[IntentKind.VERIFY] * 3)
    desk.talk("SPR-1001", "1960-01-01 and 1111", "1958-03-15 and 7832", "1958-03-14 and 0000")
    [packet] = desk.cases.opened
    assert packet.excerpt.count("[DOB]") == 3 and packet.excerpt.count("[SSN-4]") == 3


@pytest.mark.parametrize(
    "session",
    [
        Session(customer_id="SPR-1002"),  # untrusted
        Session(customer_id="SPR-1001", gate_a_trusted=True, failed_attempts=3, locked=True),
        Session(customer_id="SPR-1001", gate_a_trusted=True, gate_b_passed=True),
    ],
)
def test_credentials_are_dropped_on_every_gate_path(session: Session) -> None:
    turn = TurnContext(credentials=Credentials(dob=date(1958, 3, 14), last4="7823"))
    desk = Desk()
    deps = Deps(
        audit=desk.audit,
        registry=ToolRegistry(),
        models={},
        model_names={},
        clock=lambda: AS_OF,
        turn=turn,
        accounts=desk.accounts,
        identity=desk.identity,
        cases=desk.cases,
    )
    state = ConversationState(
        conversation_id="CV1",
        as_of=AS_OF,
        session=session,
        versions=Versions(contracts=CONTRACTS_VERSION),
    )
    identity_gate.make(deps)(state)
    assert turn.credentials is None and desk.identity.checks == 0


# ---------- #82: FR-03 at the start, and no case without a customer (owner decisions) ----------
def test_issue_82_untrusted_customer_is_told_on_the_first_turn() -> None:
    desk = Desk(
        IntentKind.PRODUCT_QUESTION,
        IntentKind.PRODUCT_QUESTION,
        drafts=(cited(FEES, "Year 5 is 3%."), cited(FEES, "Year 5 is 3%.")),
    )
    first, second = desk.talk("SPR-1002", "Is year 5 4%?", "And year 6?")
    assert first.outcome is Outcome.ANSWERED and "3%" in first.reply_text
    assert CONTACT in first.reply_text and "date of birth" not in first.reply_text.lower()
    assert CONTACT not in second.reply_text  # told at the start, not on every turn


def test_issue_82_g_b2_01_states_the_notice_once() -> None:
    desk = Desk(IntentKind.ACCOUNT_INFO)
    [r] = desk.talk("SPR-1002", "What's my current balance?")
    assert r.outcome is Outcome.NOT_PERMITTED and r.reply_text.count(CONTACT) == 1


def test_issue_82_trusted_customer_gets_no_notice() -> None:
    desk = Desk(IntentKind.PRODUCT_QUESTION, drafts=(cited(FEES, "Year 5 is 3%."),))
    [r] = desk.talk("SPR-1001", "Is year 5 4%?")
    assert CONTACT not in r.reply_text


def test_issue_82_anonymous_third_party_gets_no_case() -> None:
    desk = Desk(IntentKind.THIRD_PARTY)
    [r] = desk.talk(None, "I handle my mum's finances. What's her balance?")
    assert r.outcome is Outcome.NOT_PERMITTED
    assert Step.CREATE_CASE not in r.steps and desk.cases.opened == []
    assert CONTACT in r.reply_text and r.reference is None
