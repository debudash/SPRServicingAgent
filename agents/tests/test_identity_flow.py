"""Identity end to end with scripted models and in-memory stores: login, Gate A, the step-up.

Issue #59 built the B2 flow with the challenge typed into chat. Issue #102 (ADR 0007) moves the
session start to a login and the challenge to a step-up form before money moves, so these tests
follow the login flow. Each earlier regression keeps its intent: G-B2-01..06, BH-B2-01/02, #73,
#74, #82, #84 and the review hand-offs from PR #61 and PR #72.
"""

import re
import sqlite3
from datetime import date

import pytest

from agents.guards.credentials import Credentials
from agents.nodes import identity_gate
from agents.nodes.common import Deps, Stores, TurnContext
from agents.nodes.knowledge import KnowledgeDraft
from agents.runner import GraphDeskRunner
from agents.testing import (
    MemoryAccounts,
    MemoryCases,
    MemoryIdentity,
    MemoryPasswords,
    MemoryProposals,
    MemoryQuotes,
    ScriptedChatModel,
    put_pending_confirmation,
)
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
from contracts.ports import AuditEvent, LoginDeskRunner, LoginRefused, TurnResult
from contracts.state import ConversationState, GateResult, Session, TraceEvent, Versions
from contracts.tools import Node, Role, Step

from .test_graph import FEES, FakeSearch, MemoryAudit, cited

AS_OF = date(2024, 12, 1)
CONTACT = "1-800-555-0192"
RIGHT = (date(1958, 3, 14), "7823")
WRONG = [(date(1960, 1, 1), "1111"), (date(1958, 3, 15), "7832"), (date(1958, 3, 14), "0000")]
PASSWORDS = {
    "SPR-1001": "margaret-demo",
    "SPR-1002": "raymond-demo",
    "SPR-1003": "linda-demo",
    "SPR-1004": "thomas-demo",
}


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
    "SPR-1001": RIGHT,
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
        accounts: MemoryAccounts | None = None,
    ) -> None:
        self.search = FakeSearch([FEES])
        self.concierge = ScriptedChatModel([Intent(kind=k) for k in kinds])
        self.audit = MemoryAudit()
        self.accounts = accounts or MemoryAccounts(
            views or VIEWS, trusted={"SPR-1001", "SPR-1003", "SPR-1004"}
        )
        self.identity = MemoryIdentity(STORED)
        self.passwords = MemoryPasswords(PASSWORDS)
        self.cases = cases or MemoryCases()
        self.runner = GraphDeskRunner(
            search=self.search,
            audit=self.audit,
            models={Role.CONCIERGE: self.concierge, Role.KNOWLEDGE: ScriptedChatModel(drafts)},
            clock=lambda: AS_OF,
            stores=Stores(
                accounts=self.accounts,
                identity=self.identity,
                cases=self.cases,
                passwords=self.passwords,
                quotes=MemoryQuotes(),
                proposals=MemoryProposals(),
            ),
        )

    def login(self, customer: str) -> str:
        conv = self.runner.login(customer, PASSWORDS[customer])
        assert isinstance(conv, str)
        self.conv = conv
        return conv

    def talk(self, customer: str | None, *texts: str) -> list[TurnResult]:
        """Log in as `customer` (None: a guest session), then send each text."""
        if customer is None:
            self.conv = self.runner.start(None)
        else:
            self.login(customer)
        return [self.runner.send(self.conv, t) for t in texts]

    def step_ups(self, *answers: tuple[date, str]) -> list[TurnResult]:
        """A confirmed withdrawal waiting for the step-up (#88 builds the confirm), then the
        form submissions."""
        put_pending_confirmation(self.runner, self.conv)
        return [self.runner.step_up(self.conv, dob, last4) for dob, last4 in answers]

    def state(self) -> ConversationState:
        return self.runner._states[self.conv]

    def events(self) -> list[AuditEvent]:
        return [r.event for r in self.audit.rows]

    def everything_kept(self) -> str:
        s = self.state()
        return without_generated(
            " ".join(
                [
                    s.model_dump_json(),
                    " ".join(r.model_dump_json() for r in self.audit.rows),
                    " ".join(p.model_dump_json() for p in self.cases.opened),
                    " ".join(str(m.content) for call in self.concierge.calls for m in call),
                ]
            )
        )


# Issue #159 (found by CI on PR #157): audit rows carry wall-clock timestamps with microseconds and
# IDs carry random hex, so the restricted-value checks below failed by chance on 0000, 1111 or 1958
# with nothing leaked. Only generated values are masked: an ISO timestamp, or an ID with one of the
# desk's prefixes. A bare digit run (a compact date of birth, SSN digits) is still checked.
_GENERATED = re.compile(
    r"\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})?"
    r"|\b(?:conv|prop|CASE|appr|TX)-[0-9A-Fa-f]+\b"
)


def without_generated(text: str) -> str:
    return _GENERATED.sub("<generated>", text)


def test_issue_159_only_generated_values_are_masked() -> None:
    # Issue #159, found by CI on PR #157: the check failed on a timestamp's microseconds.
    text = "at 2026-11-11T02:29:14.000012+00:00 conv-a0000b CASE-1958AB11 TX-11110000 dob 19580314"
    masked = without_generated(text)
    assert "0000" not in masked.replace("19580314", "")
    assert "1111" not in masked and "19580314" in masked  # a compact date of birth still shows


def test_the_runner_is_a_login_runner() -> None:
    runner: LoginDeskRunner = Desk().runner
    assert runner


# ---------- the login (ADR 0007) ----------
def test_a_wrong_password_is_refused_and_opens_nothing() -> None:
    desk = Desk()
    before = dict(desk.runner._states)
    for customer, password in [("SPR-1001", "wrong"), ("SPR-9999", "x"), ("SPR-1001", "")]:
        assert desk.runner.login(customer, password) == LoginRefused()
    assert desk.runner._states == before


def test_a_login_binds_the_customer_and_marks_the_session_authenticated() -> None:
    desk = Desk()
    desk.login("SPR-1001")
    s = desk.state().session
    assert s.customer_id == "SPR-1001" and s.authenticated and not s.gate_b_passed


# ---------- G-B2-01: Raymond logs in, and Gate A still turns him away (GR-14) ----------
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
    assert desk.state().session.gate_a_trusted is False
    assert not r.step_up_required


# ---------- G-B2-02 / BH-B2-02: logged in and trusted, so the balance with no challenge ----------
def test_bh_b2_02_login_then_balance() -> None:
    desk = Desk(IntentKind.ACCOUNT_INFO)
    [r] = desk.talk("SPR-1001", "What's my balance?")
    assert r.outcome is Outcome.ANSWERED
    assert r.steps == (Step.GET_ACCOUNT,)
    assert "$87,450.62" in r.reply_text
    assert r.nodes == (
        Node.INTAKE,
        Node.CONCIERGE,
        Node.IDENTITY_GATE,
        Node.ACCOUNT,
        Node.RESPOND,
    )
    assert desk.identity.checks == 0
    assert desk.state().trace[-1:] == [TraceEvent(turn=1, node=Node.ACCOUNT, step=Step.GET_ACCOUNT)]
    assert not r.step_up_required


def test_g_b2_02_nothing_ever_asks_for_credentials_in_chat() -> None:
    desk = Desk(IntentKind.ACCOUNT_INFO, IntentKind.VERIFY)
    for r in desk.talk("SPR-1001", "What's my balance?", "I'd like to verify my identity"):
        assert "date of birth" not in r.reply_text.lower()
        assert "last four" not in r.reply_text.lower()


# ---------- G-B2-03: later account turns need no new check ----------
def test_g_b2_03_logged_in_customer_gets_the_balance_again_without_a_check() -> None:
    desk = Desk(IntentKind.ACCOUNT_INFO, IntentKind.ACCOUNT_INFO)
    _, r = desk.talk("SPR-1001", "What's my balance?", "And my balance now?")
    assert r.outcome is Outcome.ANSWERED and r.steps == (Step.GET_ACCOUNT,)
    assert desk.identity.checks == 0


# ---------- G-B2-04: the owner asking for their own restricted fields (NG-08) ----------
def test_g_b2_04_restricted_fields_are_never_read_back() -> None:
    desk = Desk(IntentKind.RESTRICTED_INFO)
    [r] = desk.talk(
        "SPR-1001", "Can you read me back the SSN and date of birth you have on file for me?"
    )
    assert r.outcome is Outcome.NOT_PERMITTED
    for leaked in ("7823", "1958-03-14", "03/14/1958"):
        assert leaked not in r.reply_text
    assert Step.GET_ACCOUNT not in r.steps


# ---------- G-B2-05: another customer's account (NG-05) ----------
def test_g_b2_05_another_account_gets_nothing() -> None:
    desk = Desk(IntentKind.OTHER_ACCOUNT)
    [r] = desk.talk("SPR-1001", "What's the balance on account SPR-1004? It's my brother's.")
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
    assert "11,200" not in r.reply_text
    [packet] = desk.cases.opened
    assert packet.opened_for is CaseReason.THIRD_PARTY and packet.customer_id == "SPR-1003"
    assert r.reference == packet.case_id and packet.case_id in r.reply_text
    assert desk.accounts.viewed == []
    case_rows = [row for row in desk.audit.rows if row.event is AuditEvent.CASE_OPENED]
    assert [row.case_id for row in case_rows] == [packet.case_id]


# ---------- the step-up (ADR 0007): the form's values, never chat text ----------
def test_a_passed_step_up_is_recorded_and_its_values_kept_nowhere() -> None:
    desk = Desk()
    desk.login("SPR-1001")
    [r] = desk.step_ups(RIGHT)
    # #89: a pass continues the confirmed withdrawal. This desk has no money path, so the kill
    # switch reads off and the withdrawal goes to a person (FR-26). No model node runs.
    assert r.steps == (Step.VERIFY_IDENTITY, Step.CREATE_CASE)
    assert r.nodes == (Node.INTAKE, Node.IDENTITY_GATE, Node.RULES, Node.CASE, Node.RESPOND)
    assert r.outcome is Outcome.NEEDS_HUMAN
    assert desk.state().session.gate_b_passed and not r.step_up_required
    assert AuditEvent.GATE_B_PASSED in desk.events()
    step = TraceEvent(turn=1, node=Node.IDENTITY_GATE, step=Step.VERIFY_IDENTITY)
    assert step in desk.state().trace
    assert desk.concierge.calls == []
    kept = desk.everything_kept()
    for value in ("7823", "1958-03-14", "1958"):
        assert value not in kept


def test_a_failed_step_up_says_so_counts_and_asks_for_the_form_again() -> None:
    desk = Desk()
    desk.login("SPR-1001")
    [r] = desk.step_ups(WRONG[0])
    assert r.outcome is Outcome.NOT_PERMITTED and r.steps == (Step.VERIFY_IDENTITY,)
    assert "don't match" in r.reply_text and "2 more tries" in r.reply_text
    assert "date of birth" not in r.reply_text.lower()  # the form asks, not the chat
    assert desk.state().session.failed_attempts == 1
    assert r.step_up_required  # the UI shows the form again


def test_a_step_up_with_nothing_pending_counts_nothing() -> None:
    desk = Desk()
    desk.login("SPR-1001")
    r = desk.runner.step_up(desk.conv, *WRONG[0])
    assert r.outcome is Outcome.NOT_PERMITTED
    assert desk.identity.checks == 0 and desk.state().session.failed_attempts == 0
    assert not r.step_up_required
    assert desk.audit.rows[-1].event is AuditEvent.REFUSED  # every turn writes its audit row


def test_a_guest_cannot_step_up() -> None:
    desk = Desk()
    desk.talk(None)
    r = desk.runner.step_up(desk.conv, *RIGHT)
    assert r.outcome is Outcome.NOT_PERMITTED and desk.identity.checks == 0


# ---------- BH-B2-01: three failed step-ups lock the session and open a case (D-08) ----------
def test_bh_b2_01_three_failures_lock_and_the_right_answer_no_longer_unlocks() -> None:
    desk = Desk(IntentKind.ACCOUNT_INFO)
    desk.login("SPR-1001")
    turns = desk.step_ups(*WRONG, RIGHT)
    assert [t.outcome for t in turns] == [Outcome.NOT_PERMITTED] * 4
    assert desk.identity.checks == 3  # the locked fourth try is never checked
    locking = turns[2]
    assert Step.CREATE_CASE in locking.steps
    [packet] = desk.cases.opened
    assert packet.opened_for is CaseReason.LOCKED and locking.reference == packet.case_id
    events = desk.events()
    assert events.count(AuditEvent.GATE_B_FAILED) == 3
    assert AuditEvent.LOCKED in events and AuditEvent.CASE_OPENED in events
    assert desk.state().session.locked and not desk.state().session.gate_b_passed
    assert not turns[3].step_up_required
    for digits in ("7823", "7832", "1111", "0000", "1958", "1960"):
        assert digits not in desk.everything_kept()
    # Locked: the account is shut for the session too (FR-04, #107).
    after = desk.runner.send(desk.conv, "What's my balance?")
    assert after.outcome is Outcome.NOT_PERMITTED and "87,450.62" not in after.reply_text
    assert Step.GET_ACCOUNT not in after.steps


# ---------- credentials typed into chat are masked and never checked (ADR 0007) ----------
def test_credentials_typed_in_chat_are_never_checked() -> None:
    desk = Desk(IntentKind.VERIFY)
    [r] = desk.talk("SPR-1001", "My date of birth is 1958-03-14 and the last four are 7823.")
    assert desk.identity.checks == 0 and Step.VERIFY_IDENTITY not in r.steps
    assert not desk.state().session.gate_b_passed
    for value in ("7823", "1958-03-14"):
        assert value not in desk.everything_kept()


def test_a_guest_asking_about_an_account_is_told_to_log_in() -> None:
    desk = Desk(IntentKind.ACCOUNT_INFO)
    [r] = desk.talk(None, "What's my balance?")
    assert r.outcome is Outcome.NOT_PERMITTED
    assert "log in" in r.reply_text.lower() and "date of birth" not in r.reply_text.lower()
    assert desk.identity.checks == 0 and desk.accounts.viewed == []


def test_a_bound_session_that_never_logged_in_gets_no_account() -> None:
    # start(customer_id) remains until contracts 0.7.0 (#105); it is not a login.
    desk = Desk(IntentKind.ACCOUNT_INFO)
    desk.conv = desk.runner.start("SPR-1001")
    r = desk.runner.send(desk.conv, "What's my balance?")
    assert r.outcome is Outcome.NOT_PERMITTED and "log in" in r.reply_text.lower()
    assert desk.accounts.viewed == []


# ---------- hand-offs from the review of PR #61 ----------
def test_gate_and_account_view_do_not_outlive_their_turn() -> None:
    desk = Desk(IntentKind.ACCOUNT_INFO, IntentKind.OUT_OF_SCOPE)
    first, _ = desk.talk("SPR-1001", "What's my balance?", "Should I buy bitcoin instead?")
    assert first.outcome is Outcome.ANSWERED
    state = desk.state()
    assert state.gate is None and state.account_view is None and state.case_packet is None
    assert state.session.authenticated  # the session, unlike the per-turn fields, persists


def test_gate_result_is_recorded_with_its_session() -> None:
    desk = Desk(IntentKind.ACCOUNT_INFO)
    desk.talk("SPR-1001", "What's my balance?")
    state = desk.state()
    assert state.gate is GateResult.LOGGED_IN and state.session.authenticated
    desk.step_ups(RIGHT)
    state = desk.state()
    assert state.gate is GateResult.PASSED and state.session.gate_b_passed


def test_a_state_validation_error_fails_closed_as_a_contract_violation() -> None:
    # A store bug that hands back another customer's view must not reach the customer: the
    # state refuses it (NG-05) and the turn ends UNAVAILABLE, not as a provider error.
    desk = Desk(IntentKind.ACCOUNT_INFO, views={**VIEWS, "SPR-1001": VIEWS["SPR-1004"]})
    [r] = desk.talk("SPR-1001", "What's my balance?")
    assert r.outcome is Outcome.UNAVAILABLE
    assert not r.provider_error
    assert "210,000" not in r.reply_text


# ---------- #73: the lockout was lost when opening the lock case failed ----------
# Found by /code-review on PR #72 (spec). D-08, GR-21: the lock holds if the case store fails.
class BrokenCases(MemoryCases):
    def open(self, packet: CasePacket) -> None:
        raise sqlite3.OperationalError("database is locked")


def test_issue_73_lock_holds_when_the_case_store_fails() -> None:
    desk = Desk(cases=BrokenCases())
    desk.login("SPR-1001")
    turns = desk.step_ups(*WRONG, RIGHT)
    session = desk.state().session
    assert session.locked and session.failed_attempts == 3
    assert desk.identity.checks == 3  # the right answer after the lock is never checked
    locking = turns[2]
    assert not locking.provider_error
    assert locking.outcome is Outcome.NOT_PERMITTED
    assert CONTACT in locking.reply_text and "case" in locking.reply_text.lower()
    assert turns[3].outcome is Outcome.NOT_PERMITTED and not session.gate_b_passed


# ---------- #74: credentials in a turn swallowed the customer's actual request ----------
# Found by /code-review on PR #72 (spec). GR-20: the outcome is about what the customer asked.
# Since ADR 0007 typed credentials are masked and ignored, so the request always stands alone.
MIXED = "DOB 1958-03-14, last four of SSN 7823. Is the year 5 surrender charge 4%?"


def test_issue_74_credentials_with_a_product_question_get_the_answer() -> None:
    desk = Desk(IntentKind.PRODUCT_QUESTION, drafts=(cited(FEES, "Year 5 is 3%."),))
    [r] = desk.talk("SPR-1001", MIXED)
    assert r.steps == (Step.SEARCH_KB,)
    assert r.outcome is Outcome.ANSWERED and "3%" in r.reply_text
    assert desk.identity.checks == 0


def test_issue_74_guest_credentials_with_a_product_question_get_the_answer() -> None:
    desk = Desk(IntentKind.PRODUCT_QUESTION, drafts=(cited(FEES, "Year 5 is 3%."),))
    [r] = desk.talk(None, MIXED)
    assert r.outcome is Outcome.ANSWERED and "3%" in r.reply_text
    assert "log in" not in r.reply_text.lower()
    assert desk.identity.checks == 0


@pytest.mark.parametrize("stepped_up_first", [False, True])
def test_issue_74_credentials_with_an_unbuilt_request_are_never_answered(
    stepped_up_first: bool,
) -> None:
    # A withdrawal was the unbuilt request until #88 built it, a full surrender until #146 (B4);
    # changing contact details still is.
    desk = Desk(IntentKind.CHANGE_DETAILS)
    desk.login("SPR-1001")
    if stepped_up_first:  # even a session that passed the step-up gets no unbuilt answer
        desk.step_ups(RIGHT)
    checks = desk.identity.checks
    r = desk.runner.send(desk.conv, "1958-03-14 and 7823, change my address please")
    assert r.outcome is Outcome.NOT_PERMITTED
    assert "yet" in r.reply_text
    assert desk.identity.checks == checks  # the typed credentials are never checked


# ---------- review follow-ups on PR #72 ----------
def test_the_lock_case_excerpt_covers_the_conversation_masked() -> None:
    desk = Desk(IntentKind.PRODUCT_QUESTION, drafts=(cited(FEES, "Year 5 is 3%."),))
    desk.talk("SPR-1001", "My dob is 1958-03-14, is year 5 4%?")
    desk.step_ups(*WRONG)
    [packet] = desk.cases.opened
    assert "[DOB]" in packet.excerpt and "1958" not in packet.excerpt
    # It covers the conversation: the chat turn and all three attempts, never their values.
    assert packet.excerpt.count("identity check submitted") == 3


@pytest.mark.parametrize(
    "session",
    [
        Session(customer_id="SPR-1002", authenticated=True),  # untrusted
        Session(
            customer_id="SPR-1001",
            gate_a_trusted=True,
            authenticated=True,
            failed_attempts=3,
            locked=True,
        ),
        Session(
            customer_id="SPR-1001", gate_a_trusted=True, authenticated=True, gate_b_passed=True
        ),
        Session(customer_id="SPR-1001", gate_a_trusted=True, authenticated=True),  # not a step-up
    ],
)
def test_credentials_are_dropped_on_every_gate_path(session: Session) -> None:
    turn = TurnContext(credentials=Credentials(dob=RIGHT[0], last4=RIGHT[1]))
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
        proposals=MemoryProposals(),
    )
    state = ConversationState(
        conversation_id="CV1",
        as_of=AS_OF,
        session=session,
        versions=Versions(contracts=CONTRACTS_VERSION),
    )
    identity_gate.make(deps)(state)
    assert turn.credentials is None and desk.identity.checks == 0


def test_logged_in_is_the_gate_for_a_login_without_a_step_up() -> None:
    desk = Desk()
    deps = Deps(
        audit=desk.audit,
        registry=ToolRegistry(),
        models={},
        model_names={},
        clock=lambda: AS_OF,
        turn=TurnContext(),
        accounts=desk.accounts,
        identity=desk.identity,
        cases=desk.cases,
        proposals=MemoryProposals(),
    )
    state = ConversationState(
        conversation_id="CV1",
        as_of=AS_OF,
        session=Session(customer_id="SPR-1001", gate_a_trusted=True, authenticated=True),
        versions=Versions(contracts=CONTRACTS_VERSION),
    )
    assert identity_gate.make(deps)(state) == {"gate": GateResult.LOGGED_IN}


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


def test_issue_82_guest_third_party_gets_no_case() -> None:
    desk = Desk(IntentKind.THIRD_PARTY)
    [r] = desk.talk(None, "I handle my mum's finances. What's her balance?")
    assert r.outcome is Outcome.NOT_PERMITTED
    assert Step.CREATE_CASE not in r.steps and desk.cases.opened == []
    assert CONTACT in r.reply_text and r.reference is None


# ---------- #84: the first-turn notice was lost when turn 1 failed ----------
# Found by /code-review on PR #83 (spec). FR-03: told in the desk's first real reply.
class FlakyAccounts(MemoryAccounts):
    def __init__(self) -> None:
        super().__init__(VIEWS, trusted={"SPR-1001"})
        self.calls = 0

    def gate_a(self, customer_id: str) -> bool:
        self.calls += 1
        if self.calls == 1:
            raise sqlite3.OperationalError("database is locked")
        return super().gate_a(customer_id)


def test_issue_84_notice_comes_on_the_first_real_reply_after_a_failed_turn() -> None:
    drafts = (cited(FEES, "Year 5 is 3%."), cited(FEES, "Year 5 is 3%."))
    desk = Desk(*[IntentKind.PRODUCT_QUESTION] * 3, drafts=drafts, accounts=FlakyAccounts())
    failed, first_real, later = desk.talk("SPR-1002", "Is year 5 4%?", "Is year 5 4%?", "Year 6?")
    assert failed.outcome is Outcome.UNAVAILABLE
    assert first_real.outcome is Outcome.ANSWERED and CONTACT in first_real.reply_text
    assert CONTACT not in later.reply_text


# ---------- #114: withdrawal amounts were masked as SSN digits for every logged-in customer ----
# Found by /code-review on PR #113 (spec): "withdraw 5000" reached the model as "[SSN-4]".
def _seen_by_concierge(desk: Desk) -> str:
    return " ".join(str(m.content) for call in desk.concierge.calls for m in call)


def test_issue_114_a_logged_in_customers_amount_stays_an_amount() -> None:
    desk = Desk(IntentKind.WITHDRAWAL)
    desk.talk("SPR-1001", "I want to withdraw 5000")
    assert "withdraw 5000" in _seen_by_concierge(desk)
    assert "withdraw 5000" in desk.state().transcript[0].text


def test_issue_114_a_bare_last_four_is_masked_while_the_step_up_is_shown() -> None:
    desk = Desk(IntentKind.OTHER)
    desk.login("SPR-1001")
    put_pending_confirmation(desk.runner, desk.conv)
    desk.runner.send(desk.conv, "7823")  # typed into chat instead of the form
    assert "7823" not in desk.everything_kept()


def test_issue_114_a_last_four_after_a_dob_turn_is_still_masked() -> None:
    # The #67 case (a DOB, then the last four on its own next turn) keeps its mask.
    desk = Desk(IntentKind.OTHER, IntentKind.OTHER)
    desk.talk("SPR-1001", "My date of birth is 1958-03-14.", "7823")
    assert "7823" not in desk.everything_kept() and "1958-03-14" not in desk.everything_kept()


# ---------- #115: a refused step-up kept the previous turn's gate, account view and case ----------
# Found by /code-review on PR #113 (spec): one turn's decision never stands in for the next.
def test_issue_115_a_refused_step_up_carries_no_earlier_turn_results() -> None:
    desk = Desk(IntentKind.ACCOUNT_INFO)
    [balance] = desk.talk("SPR-1001", "What's my balance?")
    assert balance.outcome is Outcome.ANSWERED
    desk.runner.step_up(desk.conv, *RIGHT)  # nothing pending: refused
    state = desk.state()
    assert state.gate is None and state.account_view is None and state.case_packet is None
    assert state.reply is None or "87,450.62" not in state.reply.text


# ---------- #116: a malformed step-up counted as a failed identity attempt ----------
# Found by /code-review on PR #113 (both axes). ADR 0005: nothing usable is not an attempt.
@pytest.mark.parametrize("last4", ["", "123", "12345", "12a4", " 782"])
def test_issue_116_a_malformed_last_four_counts_nothing(last4: str) -> None:
    desk = Desk()
    desk.login("SPR-1001")
    [r] = desk.step_ups((RIGHT[0], last4))
    assert r.outcome is Outcome.NOT_PERMITTED
    assert desk.identity.checks == 0 and desk.state().session.failed_attempts == 0
    assert r.step_up_required  # still pending: the form is shown again
    assert desk.audit.rows[-1].event is AuditEvent.REFUSED


# ---------- review follow-ups on PR #113 ----------
def test_a_step_up_on_a_session_that_never_logged_in_is_told_to_log_in() -> None:
    desk = Desk()
    desk.conv = desk.runner.start("SPR-1001")  # bound, no login (until contracts 0.7.0)
    put_pending_confirmation(desk.runner, desk.conv)
    r = desk.runner.step_up(desk.conv, *RIGHT)
    assert r.outcome is Outcome.NOT_PERMITTED and "log in" in r.reply_text.lower()
    assert desk.identity.checks == 0


# ---------- #172: the account summary at the top of the chat (contracts 0.6.3) ----------
def test_issue_172_a_logged_in_trusted_customer_gets_their_account_summary() -> None:
    desk = Desk()
    desk.login("SPR-1001")
    assert desk.runner.account(desk.conv) == VIEWS["SPR-1001"]  # before any turn: Gate A read live


def test_issue_172_an_untrusted_account_gets_no_summary() -> None:
    desk = Desk()
    desk.login("SPR-1002")  # GR-14: the same refusal the gate gives a balance question
    assert desk.runner.account(desk.conv) is None
    assert desk.accounts.viewed == []


def test_issue_172_a_guest_or_a_session_without_a_login_gets_no_summary() -> None:
    desk = Desk()
    assert desk.runner.account(desk.runner.start(None)) is None
    assert desk.runner.account(desk.runner.start("SPR-1001")) is None  # bound is not logged in
    assert desk.accounts.viewed == []


def test_issue_172_a_locked_session_gets_no_summary() -> None:
    desk = Desk(IntentKind.ACCOUNT_INFO)
    desk.login("SPR-1001")
    desk.step_ups(*WRONG)
    assert desk.state().session.locked
    assert desk.runner.account(desk.conv) is None  # FR-04: the account is shut for the session


def test_issue_172_trust_withdrawn_after_login_hides_the_summary() -> None:
    desk = Desk()
    desk.login("SPR-1001")
    desk.accounts.trusted.discard("SPR-1001")  # Gate A is read live, not from the login
    assert desk.runner.account(desk.conv) is None


def test_issue_172_the_summary_agrees_with_the_gate_for_every_session_kind() -> None:
    """Review on PR #173: account() restates the gate's rule, so pin the two together. For each
    kind of session, the header shows figures exactly when a balance question reaches the
    account."""

    def guest(d: Desk) -> None:
        d.conv = d.runner.start(None)

    def bound(d: Desk) -> None:
        d.conv = d.runner.start("SPR-1001")

    def locked(d: Desk) -> None:
        d.login("SPR-1001")
        d.step_ups(*WRONG)

    def verified(d: Desk) -> None:
        d.login("SPR-1001")
        d.step_ups(RIGHT)

    kinds = {
        "trusted login": lambda d: d.login("SPR-1001"),
        "untrusted login": lambda d: d.login("SPR-1002"),
        "guest": guest,
        "bound without login": bound,
        "locked": locked,
        "step-up passed": verified,
    }
    for name, open_session in kinds.items():
        desk = Desk(IntentKind.ACCOUNT_INFO)
        open_session(desk)
        shown = desk.runner.account(desk.conv) is not None
        reached = Step.GET_ACCOUNT in desk.runner.send(desk.conv, "What's my balance?").steps
        assert shown == reached, name


# ---------- #176: the desk could not say when the contract started ----------
def test_issue_176_the_account_reply_states_the_contract_start_date() -> None:
    """#176, found by the owner in the local desk: "when did my contract start?" got the balance."""
    view = VIEWS["SPR-1001"].model_copy(update={"contract_start_date": date(2022, 6, 1)})
    desk = Desk(IntentKind.ACCOUNT_INFO, views={**VIEWS, "SPR-1001": view})
    [r] = desk.talk("SPR-1001", "When did my contract start?")
    assert r.outcome is Outcome.ANSWERED
    assert "Your contract started on June 1, 2022" in r.reply_text
    assert "87,450.62" in r.reply_text  # the balance is still there


# ---------- #177: a greeting got a NOT_PERMITTED refusal ----------
def test_issue_177_a_greeting_gets_a_friendly_answer_not_a_refusal() -> None:
    """#177, found by the owner in the local desk: "hi" was refused as NOT_PERMITTED."""
    for customer in ("SPR-1001", None):  # logged in, and a guest
        desk = Desk(IntentKind.OTHER)
        [r] = desk.talk(customer, "hi")
        assert r.outcome is Outcome.ANSWERED, customer
        assert r.reply_text.startswith("Hello"), r.reply_text
        assert "isn't available" not in r.reply_text


# ---------- #183: the review message did not say clearly what happens next ----------
def test_issue_183_the_review_message_says_submitted_and_a_person_will_reach_out() -> None:
    """#183, asked by the owner: say plainly it is submitted and the team will be in touch."""
    from agents.nodes.respond import _review_text

    text = _review_text("CASE-ABC123")
    assert "submitted for review" in text and "CASE-ABC123" in text
    assert "Nothing has been paid" in text
    assert "once the review is complete" in text
