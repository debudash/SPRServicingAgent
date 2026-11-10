"""Rules, Compliance, the approval token and execute (#89, ARCHITECTURE 3.3) over the real SQLite
stores and ledger, offline.

The Concierge and Compliance are scripted; the rules, the approval edge, the ApprovalStore and the
ledger are the real ones. Each FR-08 precondition is removed one at a time and the count of
executions must be zero (M-01).
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from agents.nodes.compliance import ComplianceDraft, DraftReason
from agents.runner import GraphDeskRunner
from agents.testing import MemoryPolicy, ScriptedChatModel
from agents.wiring import build_stores, money_path, open_desk_db
from contracts.messages import CaseReason, Intent, IntentKind, ProposalStatus, Signal
from contracts.outcomes import Outcome
from contracts.ports import AuditEvent, KnowledgeChunk, TurnResult
from contracts.tools import Node, Role, Step

from .test_graph import FakeSearch, MemoryAudit

AS_OF = date(2024, 12, 1)
PASSWORDS = {"SPR-1001": "margaret-demo", "SPR-1004": "thomas-demo"}
MARGARET = (date(1958, 3, 14), "7823")
WRONG = (date(1960, 1, 1), "1111")
POLICY = KnowledgeChunk(
    doc_id="large_withdrawal_policy",
    version=1,
    effective_date=date(2024, 1, 1),
    section="Which withdrawals are reviewed by a person",
    text="Withdrawals up to $25,000 and half the balance may proceed after review.",
    source_path="knowledge/large_withdrawal_policy.md",
)
REF = "large_withdrawal_policy v1 §Which withdrawals are reviewed by a person"


def withdraw(dollars: int, *, yes: bool = False) -> Intent:
    return Intent(kind=IntentKind.WITHDRAWAL, amount_cents=dollars * 100, explicit_yes=yes)


def confirm(dollars: int | None = None, *, yes: bool = True) -> Intent:
    cents = None if dollars is None else dollars * 100
    return Intent(kind=IntentKind.CONFIRM, amount_cents=cents, explicit_yes=yes)


def review(decision: str = "approve", *signals: Signal, ref: str = REF) -> ComplianceDraft:
    return ComplianceDraft(
        decision=decision,
        reasons=[DraftReason(policy_ref=ref, text="Within the self-service limits.")],
        signals=list(signals),
    )


class Desk:
    def __init__(
        self,
        tmp_path: Path,
        intents: list[Intent],
        reviews: Sequence[object] = (),
        *,
        secret: bytes = b"test-secret",
        enabled: bool = True,
    ) -> None:
        self.audit = MemoryAudit()
        self.conn = open_desk_db(tmp_path / "desk.db")
        self.compliance = ScriptedChatModel(list(reviews))
        self.policy = MemoryPolicy([POLICY])
        money = money_path(self.conn, self.policy, secret=secret, execution_enabled=enabled)
        self.stores = replace(build_stores(self.conn), money=money)
        self.runner = GraphDeskRunner(
            search=FakeSearch([]),
            audit=self.audit,
            models={
                Role.CONCIERGE: ScriptedChatModel(intents),
                Role.KNOWLEDGE: ScriptedChatModel(),
                Role.COMPLIANCE: self.compliance,
            },
            clock=lambda: AS_OF,
            stores=self.stores,
        )
        self.conv = ""
        self.results: list[TurnResult] = []

    def login(self, customer: str = "SPR-1001") -> "Desk":
        conv = self.runner.login(customer, PASSWORDS[customer])
        assert isinstance(conv, str)
        self.conv = conv
        return self

    def say(self, text: str = "message") -> TurnResult:
        r = self.runner.send(self.conv, text)
        self.results.append(r)
        return r

    def step_up(self, dob: date = MARGARET[0], last4: str = MARGARET[1]) -> TurnResult:
        r = self.runner.step_up(self.conv, dob, last4)
        self.results.append(r)
        return r

    def proposal_id(self) -> str:
        proposal = self.runner._states[self.conv].proposal
        assert proposal is not None
        return proposal.proposal_id

    def status(self) -> ProposalStatus:
        return self.stores.proposals.status(self.proposal_id())

    def executions(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE is_synthetic = 0"
        ).fetchone()
        return int(row[0])

    def steps(self) -> list[Step]:
        return [s for r in self.results for s in r.steps]

    def events(self) -> list[AuditEvent]:
        return [row.event for row in self.audit.rows]


def _is_subsequence(wanted: list[Step], seen: list[Step]) -> bool:
    it = iter(seen)
    return all(any(s == w for s in it) for w in wanted)


# ---------- the happy path ----------
def test_bh_b3_01_quote_yes_step_up_compliance_execute(tmp_path: Path) -> None:
    desk = Desk(tmp_path, [withdraw(20_000), confirm(20_000)], [review()]).login()
    desk.say("I'd like to withdraw $20,000.")
    assert desk.say("Yes, please go ahead with the $20,000 withdrawal.").step_up_required
    r = desk.step_up()
    assert r.outcome is Outcome.EXECUTED
    assert r.reference is not None and r.reference.startswith("TX-")
    assert "$19,324.70" in r.reply_text and "reference" in r.reply_text
    assert _is_subsequence(
        [Step.QUOTE, Step.VERIFY_IDENTITY, Step.COMPLIANCE_REVIEW, Step.EXECUTE], desk.steps()
    )
    assert desk.executions() == 1
    assert desk.status() is ProposalStatus.EXECUTED
    for event in (AuditEvent.COMPLIANCE_DECIDED, AuditEvent.TOKEN_ISSUED):
        assert event in desk.events()
    assert not r.step_up_required


def test_bh_b3_07_a_passed_step_up_lasts_the_session(tmp_path: Path) -> None:
    intents = [withdraw(2_000), confirm(2_000), withdraw(1_000), confirm(1_000)]
    desk = Desk(tmp_path, intents, [review(), review()]).login()
    desk.say("I'd like to withdraw $2,000.")
    desk.say("Yes, go ahead with $2,000.")
    assert desk.step_up().outcome is Outcome.EXECUTED
    desk.say("And another $1,000, please.")
    second = desk.say("Yes, go ahead with $1,000.")
    assert second.outcome is Outcome.EXECUTED  # no second step-up
    assert desk.steps().count(Step.VERIFY_IDENTITY) == 1
    assert desk.executions() == 2


def test_bh_b3_04_a_repeated_yes_executes_once(tmp_path: Path) -> None:
    intents = [withdraw(5_000), confirm(5_000), confirm(5_000)]
    desk = Desk(tmp_path, intents, [review()]).login()
    desk.say("I'd like to withdraw $5,000.")
    desk.say("Yes, go ahead with $5,000.")
    assert desk.step_up().outcome is Outcome.EXECUTED
    again = desk.say("Yes, go ahead with $5,000.")
    assert again.outcome is not Outcome.EXECUTED and "Done" not in again.reply_text
    assert desk.executions() == 1  # FR-09


# ---------- BH-B3-05: a go-ahead on a human-tier quote is a case ----------
def test_bh_b3_05_go_ahead_on_a_human_tier_quote_opens_a_case(tmp_path: Path) -> None:
    desk = Desk(tmp_path, [withdraw(40_000, yes=True)]).login("SPR-1004")
    r = desk.say("I'm in year 5, so a $40,000 withdrawal costs 4% on the excess, right? Go ahead.")
    assert r.outcome is Outcome.NEEDS_HUMAN
    assert "$570.00" in r.reply_text and "$39,430.00" in r.reply_text and "3%" in r.reply_text
    assert _is_subsequence([Step.GET_ACCOUNT, Step.QUOTE, Step.CREATE_CASE], list(r.steps))
    assert desk.status() is ProposalStatus.ESCALATED
    assert desk.executions() == 0
    [case_id] = [row.case_id for row in desk.audit.rows if row.event is AuditEvent.CASE_OPENED]
    assert r.reference == case_id
    assert desk.compliance.calls == []


# ---------- M-01: every FR-08 precondition removed, one at a time ----------
def test_no_step_up_no_execution(tmp_path: Path) -> None:
    desk = Desk(tmp_path, [withdraw(5_000), confirm(5_000)], [review()]).login()
    desk.say("Withdraw $5,000.")
    r = desk.say("Yes, go ahead with $5,000.")
    assert r.step_up_required and desk.executions() == 0
    assert desk.compliance.calls == []


def test_a_failed_step_up_no_execution(tmp_path: Path) -> None:
    desk = Desk(tmp_path, [withdraw(5_000), confirm(5_000)], [review()]).login()
    desk.say("Withdraw $5,000.")
    desk.say("Yes, go ahead with $5,000.")
    r = desk.step_up(*WRONG)
    assert r.outcome is Outcome.NOT_PERMITTED and desk.executions() == 0


def test_no_quote_no_execution(tmp_path: Path) -> None:
    desk = Desk(tmp_path, [confirm(5_000)], [review()]).login()
    r = desk.say("Yes, go ahead with $5,000.")
    assert Step.EXECUTE not in r.steps and desk.executions() == 0


def test_no_explicit_yes_no_execution(tmp_path: Path) -> None:
    desk = Desk(tmp_path, [withdraw(5_000), confirm(5_000, yes=False)], [review()]).login()
    desk.say("Withdraw $5,000.")
    desk.say("Fine, whatever.")
    assert desk.step_up().outcome is Outcome.NOT_PERMITTED  # nothing pending
    assert desk.executions() == 0


@pytest.mark.parametrize("decision", ["hold", "escalate"])
def test_no_compliance_approval_no_execution(tmp_path: Path, decision: str) -> None:
    desk = Desk(tmp_path, [withdraw(5_000), confirm(5_000)], [review(decision)]).login()
    desk.say("Withdraw $5,000.")
    desk.say("Yes, go ahead with $5,000.")
    r = desk.step_up()
    assert r.outcome is Outcome.NEEDS_HUMAN and "Done" not in r.reply_text  # GR-10
    assert desk.executions() == 0
    assert desk.status() is ProposalStatus.ESCALATED
    assert AuditEvent.TOKEN_ISSUED not in desk.events()


def test_a_vulnerable_customer_signal_turns_an_approve_into_a_hold(tmp_path: Path) -> None:
    drafts = [review("approve", Signal.PRESSURE)]
    desk = Desk(tmp_path, [withdraw(5_000), confirm(5_000)], drafts).login()
    desk.say("Withdraw $5,000, my nephew says I have to do it today.")
    desk.say("Yes, go ahead with $5,000.")
    r = desk.step_up()
    assert r.outcome is Outcome.NEEDS_HUMAN and desk.executions() == 0  # FR-12


def test_an_approval_citing_no_retrieved_policy_is_escalated(tmp_path: Path) -> None:
    drafts = [review("approve", ref="made_up_policy v9 §Anything")]
    desk = Desk(tmp_path, [withdraw(5_000), confirm(5_000)], drafts).login()
    desk.say("Withdraw $5,000.")
    desk.say("Yes, go ahead with $5,000.")
    r = desk.step_up()
    assert r.outcome is Outcome.NEEDS_HUMAN and desk.executions() == 0  # FR-11


def test_the_human_tier_never_reaches_compliance(tmp_path: Path) -> None:
    desk = Desk(tmp_path, [withdraw(30_000), confirm(30_000)], [review()]).login()
    desk.say("Withdraw $30,000.")  # over $25,000 (D-02)
    desk.say("Yes, go ahead with $30,000.")
    r = desk.step_up()
    assert r.outcome is Outcome.NEEDS_HUMAN and desk.executions() == 0
    assert desk.compliance.calls == []
    assert AuditEvent.RULE_FLAGGED in desk.events()


def test_the_kill_switch_sends_every_withdrawal_to_a_person(tmp_path: Path) -> None:
    desk = Desk(tmp_path, [withdraw(5_000), confirm(5_000)], [review()], enabled=False).login()
    desk.say("Withdraw $5,000.")
    desk.say("Yes, go ahead with $5,000.")
    r = desk.step_up()
    assert r.outcome is Outcome.NEEDS_HUMAN and desk.executions() == 0  # FR-26
    assert desk.compliance.calls == []


def test_no_secret_no_token_no_execution(tmp_path: Path) -> None:
    desk = Desk(tmp_path, [withdraw(5_000), confirm(5_000)], [review()], secret=b"").login()
    desk.say("Withdraw $5,000.")
    desk.say("Yes, go ahead with $5,000.")
    r = desk.step_up()
    assert r.outcome is Outcome.UNAVAILABLE and desk.executions() == 0  # GR-21
    assert desk.status() is ProposalStatus.CONFIRMED


def test_a_compliance_failure_executes_nothing(tmp_path: Path) -> None:
    desk = Desk(tmp_path, [withdraw(5_000), confirm(5_000)], []).login()  # no scripted review
    desk.say("Withdraw $5,000.")
    desk.say("Yes, go ahead with $5,000.")
    r = desk.step_up()
    assert r.outcome is Outcome.UNAVAILABLE and desk.executions() == 0  # GR-21


# ---------- what Compliance sees ----------
def test_compliance_sees_the_proposal_and_policy_never_restricted_values(tmp_path: Path) -> None:
    desk = Desk(tmp_path, [withdraw(5_000), confirm(5_000)], [review()]).login()
    desk.say("Withdraw $5,000. My date of birth is 1958-03-14.")
    desk.say("Yes, go ahead with $5,000.")
    desk.step_up()
    seen = " ".join(str(m.content) for call in desk.compliance.calls for m in call)
    assert "$5,000.00" in seen and REF in seen
    for value in ("1958-03-14", "7823"):
        assert value not in seen
    assert desk.policy.queries  # it read the policy through its one tool


def test_the_case_for_a_held_withdrawal_names_its_proposal(tmp_path: Path) -> None:
    desk = Desk(tmp_path, [withdraw(5_000), confirm(5_000)], [review("hold")]).login()
    desk.say("Withdraw $5,000.")
    desk.say("Yes, go ahead with $5,000.")
    desk.step_up()
    row = desk.conn.execute("SELECT opened_for FROM cases").fetchone()
    assert row[0] == CaseReason.WITHDRAWAL_REVIEW.value
    assert Node.CASE in desk.results[-1].nodes


def test_every_case_reason_has_its_wording() -> None:
    # Review on PR #134: the case node's wording is keyed by CaseReason; a new reason needs one.
    from agents.nodes import case

    assert set(case._WHY) == set(CaseReason)
