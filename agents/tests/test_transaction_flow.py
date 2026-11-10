"""Quote and confirm (#88, ARCHITECTURE 3.3, ADR 0007) over the real SQLite stores, offline.

The Concierge is scripted; everything after it is the real graph: identity_gate, the transaction
node (get_account, quote, propose through the Transaction role's tool scope), confirm and respond.
The expected figures are the golden set's (G-B3-01..05, BH-B3-02/03).
"""

import re
from datetime import date
from pathlib import Path

import pytest

from agents.nodes.respond import NO_CUSTOMER_TEXT, UNTRUSTED_TEXT
from agents.runner import GraphDeskRunner
from agents.testing import ScriptedChatModel
from agents.wiring import build_stores, open_desk_db
from contracts.messages import Intent, IntentKind, ProposalStatus
from contracts.outcomes import Outcome
from contracts.ports import AuditEvent, TurnResult
from contracts.tools import Node, Role, Step

from .test_graph import FakeSearch, MemoryAudit

AS_OF = date(2024, 12, 1)
PASSWORDS = {"SPR-1001": "margaret-demo", "SPR-1002": "raymond-demo", "SPR-1003": "linda-demo"}
MARGARET = (date(1958, 3, 14), "7823")
ADVICE = re.compile(r"\b(you should|i recommend|i suggest|i advise|my advice)\b", re.IGNORECASE)


def withdraw(dollars: int, *, yes: bool = False) -> Intent:
    return Intent(kind=IntentKind.WITHDRAWAL, amount_cents=dollars * 100, explicit_yes=yes)


def confirm(dollars: int | None = None, *, yes: bool = True) -> Intent:
    cents = None if dollars is None else dollars * 100
    return Intent(kind=IntentKind.CONFIRM, amount_cents=cents, explicit_yes=yes)


class Desk:
    def __init__(self, tmp_path: Path, *intents: Intent) -> None:
        self.audit = MemoryAudit()
        self.conn = open_desk_db(tmp_path / "desk.db")
        self.stores = build_stores(self.conn)
        self.runner = GraphDeskRunner(
            search=FakeSearch([]),
            audit=self.audit,
            models={
                Role.CONCIERGE: ScriptedChatModel(list(intents)),
                Role.KNOWLEDGE: ScriptedChatModel(),
            },
            clock=lambda: AS_OF,
            stores=self.stores,
        )
        self.conv = ""

    def login(self, customer: str) -> "Desk":
        conv = self.runner.login(customer, PASSWORDS[customer])
        assert isinstance(conv, str)
        self.conv = conv
        return self

    def say(self, text: str = "message") -> TurnResult:
        return self.runner.send(self.conv, text)

    def step_up(self, dob: date, last4: str) -> TurnResult:
        return self.runner.step_up(self.conv, dob, last4)

    def proposal(self) -> tuple[str, int]:
        state = self.runner._states[self.conv]
        assert state.proposal is not None
        return state.proposal.proposal_id, state.proposal.quote.amount_cents

    def status(self, proposal_id: str) -> ProposalStatus:
        return self.stores.proposals.status(proposal_id)

    def events(self) -> list[AuditEvent]:
        return [r.event for r in self.audit.rows]


# ---------- the quote (transaction node) ----------
def test_g_b3_01_a_quote_shows_the_exact_figures_and_executes_nothing(tmp_path: Path) -> None:
    desk = Desk(tmp_path, withdraw(20_000)).login("SPR-1001")
    r = desk.say("How much would I get if I withdrew $20,000?")
    assert r.outcome is Outcome.ANSWERED
    for figure in ("$8,745.06", "$11,254.94", "$675.30", "$19,324.70", "6%"):
        assert figure in r.reply_text
    assert r.steps == (Step.GET_ACCOUNT, Step.QUOTE, Step.PROPOSE)
    assert Node.TRANSACTION in r.nodes
    assert not r.step_up_required  # a quote needs no step-up (ADR 0007)
    proposal_id, amount = desk.proposal()
    assert amount == 2_000_000
    assert desk.status(proposal_id) is ProposalStatus.QUOTED
    assert AuditEvent.QUOTE_SHOWN in desk.events()


def test_g_b3_02_the_irs_notice_is_information_not_advice(tmp_path: Path) -> None:
    desk = Desk(tmp_path, withdraw(1_000)).login("SPR-1003")
    r = desk.say("I'd like to take out $1,000. What will that cost me?")
    assert r.outcome is Outcome.ANSWERED
    assert "$1,120.00" in r.reply_text and "$1,000.00" in r.reply_text
    assert "59" in r.reply_text  # FR-06
    assert not ADVICE.search(r.reply_text)  # GR-08


def test_g_b3_03_another_amount_is_a_new_quote(tmp_path: Path) -> None:
    desk = Desk(tmp_path, withdraw(3_000)).login("SPR-1003")
    r = desk.say("What if I take $3,000 instead?")
    for figure in ("$1,880.00", "$94.00", "$2,906.00"):
        assert figure in r.reply_text


def test_a_human_tier_quote_says_a_person_reviews_it(tmp_path: Path) -> None:
    desk = Desk(tmp_path, withdraw(40_000)).login("SPR-1001")  # over 25,000 (D-02)
    r = desk.say("I'd like $40,000.")
    assert r.outcome is Outcome.ANSWERED
    assert "reviewed by our team" in r.reply_text


def test_g_b3_05_more_than_the_balance_is_refused_with_the_reason(tmp_path: Path) -> None:
    desk = Desk(tmp_path, withdraw(100_000)).login("SPR-1001")
    r = desk.say("Withdraw $100,000 please.")
    assert r.outcome is Outcome.NOT_PERMITTED  # FR-07
    assert "more than your current balance" in r.reply_text
    assert "$87,450.62" in r.reply_text
    assert Step.PROPOSE not in r.steps
    assert desk.runner._states[desk.conv].proposal is None


def test_a_withdrawal_with_no_amount_asks_for_one(tmp_path: Path) -> None:
    desk = Desk(tmp_path, Intent(kind=IntentKind.WITHDRAWAL)).login("SPR-1001")
    r = desk.say("I'd like to take some money out.")
    assert r.outcome is Outcome.ANSWERED
    assert "How much" in r.reply_text
    assert Step.QUOTE not in r.steps


@pytest.mark.parametrize(
    ("customer", "text"), [(None, NO_CUSTOMER_TEXT), ("SPR-1002", UNTRUSTED_TEXT)]
)
def test_only_a_logged_in_trusted_customer_is_quoted(
    tmp_path: Path, customer: str | None, text: str
) -> None:
    desk = Desk(tmp_path, withdraw(5_000))
    if customer is None:
        desk.conv = desk.runner.start(None)
    else:
        desk.login(customer)
    r = desk.say("Withdraw $5,000.")
    assert r.outcome is Outcome.NOT_PERMITTED
    assert text in r.reply_text
    assert Step.QUOTE not in r.steps


# ---------- the yes (confirm node) ----------
def test_an_explicit_yes_on_a_later_turn_confirms_and_asks_for_the_step_up(
    tmp_path: Path,
) -> None:
    desk = Desk(tmp_path, withdraw(20_000), confirm(20_000)).login("SPR-1001")
    desk.say("I'd like to withdraw $20,000.")
    proposal_id, _ = desk.proposal()
    r = desk.say("Yes, please go ahead with the $20,000 withdrawal.")
    assert desk.status(proposal_id) is ProposalStatus.CONFIRMED
    assert r.step_up_required  # ADR 0007: the step-up comes after the yes
    assert Node.CONFIRM in r.nodes
    assert Step.VERIFY_IDENTITY not in r.steps
    assert "identity check" in r.reply_text
    assert AuditEvent.CONFIRMED in desk.events()
    passed = desk.step_up(*MARGARET)
    assert passed.steps == (Step.VERIFY_IDENTITY,)
    assert not passed.step_up_required


def test_a_bare_yes_counts_for_the_quoted_amount(tmp_path: Path) -> None:
    desk = Desk(tmp_path, withdraw(5_000), confirm(None)).login("SPR-1001")
    desk.say("Withdraw $5,000.")
    proposal_id, _ = desk.proposal()
    assert desk.say("Yes, go ahead.").step_up_required
    assert desk.status(proposal_id) is ProposalStatus.CONFIRMED


def test_bh_b3_02_a_changed_amount_is_a_new_quote_not_a_yes(tmp_path: Path) -> None:
    desk = Desk(tmp_path, withdraw(20_000), confirm(22_000)).login("SPR-1001")
    desk.say("I'd like to withdraw $20,000.")
    first, _ = desk.proposal()
    r = desk.say("Actually make it $22,000 and go ahead.")
    assert r.outcome is Outcome.ANSWERED
    assert "$795.30" in r.reply_text and "$21,204.70" in r.reply_text
    assert not r.step_up_required
    assert Step.VERIFY_IDENTITY not in r.steps
    second, amount = desk.proposal()
    assert amount == 2_200_000 and second != first
    assert desk.status(first) is ProposalStatus.VOIDED  # GR-18: nothing carries over
    assert desk.status(second) is ProposalStatus.QUOTED


def test_bh_b3_03_an_unclear_answer_is_not_a_yes(tmp_path: Path) -> None:
    desk = Desk(tmp_path, withdraw(20_000), confirm(None, yes=False)).login("SPR-1001")
    desk.say("I'd like to withdraw $20,000.")
    proposal_id, _ = desk.proposal()
    r = desk.say("Whatever you think is best.")
    assert desk.status(proposal_id) is ProposalStatus.QUOTED
    assert not r.step_up_required
    assert "clear yes" in r.reply_text
    assert not ADVICE.search(r.reply_text)


def test_a_yes_in_the_quoting_turn_does_not_count(tmp_path: Path) -> None:
    desk = Desk(tmp_path, withdraw(5_000, yes=True)).login("SPR-1001")
    r = desk.say("Withdraw $5,000, yes, go ahead.")
    proposal_id, _ = desk.proposal()
    assert desk.status(proposal_id) is ProposalStatus.QUOTED  # GR-17: a later turn
    assert not r.step_up_required


def test_a_yes_with_nothing_quoted_confirms_nothing(tmp_path: Path) -> None:
    desk = Desk(tmp_path, confirm(None)).login("SPR-1001")
    r = desk.say("Yes, go ahead.")
    assert r.outcome is Outcome.NOT_PERMITTED
    assert "no quote" in r.reply_text
    assert not r.step_up_required


def test_a_new_quote_clears_a_yes_waiting_for_the_step_up(tmp_path: Path) -> None:
    desk = Desk(tmp_path, withdraw(5_000), confirm(5_000), withdraw(3_000)).login("SPR-1001")
    desk.say("Withdraw $5,000.")
    first, _ = desk.proposal()
    assert desk.say("Yes, go ahead with $5,000.").step_up_required
    r = desk.say("Actually, just $3,000.")
    assert not r.step_up_required  # the yes was for the old quote
    assert desk.status(first) is ProposalStatus.VOIDED
    assert desk.runner._states[desk.conv].confirmation is None


def test_a_repeated_yes_confirms_once(tmp_path: Path) -> None:
    desk = Desk(tmp_path, withdraw(5_000), confirm(5_000), confirm(5_000)).login("SPR-1001")
    desk.say("Withdraw $5,000.")
    desk.say("Yes, go ahead with $5,000.")
    r = desk.say("Yes, go ahead with $5,000.")
    assert r.step_up_required
    assert desk.events().count(AuditEvent.CONFIRMED) == 1
