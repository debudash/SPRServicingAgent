"""B4 (#146): the reviewer's desk and the requests only a person decides, offline.

The conversation runs through the real graph, SQLite stores, approval store and ledger, with the
Concierge and Compliance scripted (the harness from test_money_path). The reviewer's decision goes
through `AgentReviewDesk`, the same object the UI calls.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from agents.nodes.knowledge import KnowledgeDraft
from agents.review import AgentReviewDesk
from agents.wiring import money_path
from contracts.messages import (
    CaseReason,
    CaseStatus,
    Citation,
    Decision,
    HumanDecision,
    Intent,
    IntentKind,
    ProposalStatus,
)
from contracts.outcomes import Outcome
from contracts.ports import AuditEvent, KnowledgeChunk, ReviewDesk
from contracts.tools import Step
from data.store.cases import SqliteCaseStore

from .test_money_path import AS_OF, Desk, confirm, review, withdraw

ACCOUNTS = Path(__file__).parents[2] / "problemstmt" / "spr_starter_kit" / "data" / "accounts.json"
_STORED = {a["customer_id"]: a for a in json.loads(ACCOUNTS.read_text("utf-8"))["accounts"]}


def stored(customer: str) -> tuple[date, str]:
    a = _STORED[customer]
    return date.fromisoformat(a["dob"]), a["last4_ssn"]


def reviewer(desk: Desk, *, enabled: bool = True) -> AgentReviewDesk:
    money = desk.stores.money
    assert money is not None
    if not enabled:  # the kill switch turned off after the case opened (FR-26)
        money = money_path(desk.conn, desk.policy, secret=b"test-secret", execution_enabled=False)
    return AgentReviewDesk(
        cases=SqliteCaseStore(desk.conn),
        proposals=desk.stores.proposals,
        money=money,
        audit=desk.audit,
        clock=lambda: AS_OF,
    )


def large_withdrawal_with_a_person(tmp_path: Path) -> tuple[Desk, str]:
    """BH-B4-01's conversation: $30,000 for SPR-1004, a yes, the step-up; Compliance reviews it
    (FR-11) and the D-02 flag sends it to a person."""
    desk = Desk(tmp_path, [withdraw(30_000), confirm(30_000)], [review("escalate")])
    desk.login("SPR-1004")
    desk.say("I want to withdraw $30,000.")
    desk.say("Yes, I understand the charges. Please submit it.")
    r = desk.step_up(*stored("SPR-1004"))
    assert r.outcome is Outcome.NEEDS_HUMAN and r.reference
    return desk, r.reference


def decide(case_id: str, decision: Decision, who: str = "pat") -> HumanDecision:
    return HumanDecision(case_id=case_id, reviewer_id=who, decision=decision)


# ---------- BH-B4-01: the human approval executes ----------
def test_bh_b4_01_a_reviewer_approves_and_it_executes_once(tmp_path: Path) -> None:
    desk, case_id = large_withdrawal_with_a_person(tmp_path)
    desk_review: ReviewDesk = reviewer(desk)
    [row] = desk_review.queue(CaseStatus.OPEN)
    assert row.case_id == case_id and row.opened_for is CaseReason.WITHDRAWAL_REVIEW
    packet = desk_review.case(case_id)
    assert packet is not None and packet.quote is not None and packet.rule_flags  # FR-16
    assert packet.compliance_reasons and packet.proposal_id == row.proposal_id
    assert desk.executions() == 0  # Compliance could not approve it (D-02, #137)

    result = desk_review.decide(decide(case_id, Decision.APPROVE))
    assert result.outcome is Outcome.EXECUTED and result.reference.startswith("TX-")
    assert "$30,000.00" in result.text and "$29,730.00" in result.text
    assert desk.executions() == 1
    assert desk.status() is ProposalStatus.EXECUTED
    assert desk_review.queue(CaseStatus.APPROVED)[0].decided_by == "human:pat"
    (approved_by,) = desk.conn.execute("SELECT approved_by FROM transactions").fetchone()
    assert approved_by == "human:pat"  # the human approval authorised it, not Compliance
    # The order BH-B4-01 expects: quote, compliance_review, create_case, then the person.
    steps = desk.steps()
    assert steps.index(Step.QUOTE) < steps.index(Step.COMPLIANCE_REVIEW)
    assert steps.index(Step.COMPLIANCE_REVIEW) < steps.index(Step.CREATE_CASE)
    assert AuditEvent.HUMAN_DECIDED in desk.events()


def test_an_approved_case_cannot_be_approved_again(tmp_path: Path) -> None:
    desk, case_id = large_withdrawal_with_a_person(tmp_path)
    desk_review = reviewer(desk)
    desk_review.decide(decide(case_id, Decision.APPROVE))
    with pytest.raises(ValueError):
        desk_review.decide(decide(case_id, Decision.APPROVE, who="sam"))
    assert desk.executions() == 1  # FR-09


def test_a_reject_voids_the_withdrawal(tmp_path: Path) -> None:
    desk, case_id = large_withdrawal_with_a_person(tmp_path)
    result = reviewer(desk).decide(decide(case_id, Decision.REJECT))
    assert result.outcome is Outcome.NOT_PERMITTED
    assert desk.status() is ProposalStatus.VOIDED and desk.executions() == 0


def test_request_info_then_approve(tmp_path: Path) -> None:
    desk, case_id = large_withdrawal_with_a_person(tmp_path)
    desk_review = reviewer(desk)
    asked = desk_review.decide(decide(case_id, Decision.REQUEST_INFO))
    assert asked.outcome is Outcome.NEEDS_HUMAN and desk.executions() == 0
    assert desk.status() is ProposalStatus.ESCALATED
    done = desk_review.decide(decide(case_id, Decision.APPROVE, who="sam"))
    assert done.outcome is Outcome.EXECUTED and desk.executions() == 1


def test_the_kill_switch_holds_against_a_reviewer(tmp_path: Path) -> None:
    desk, case_id = large_withdrawal_with_a_person(tmp_path)
    result = reviewer(desk, enabled=False).decide(decide(case_id, Decision.APPROVE))
    assert result.outcome is Outcome.NOT_PERMITTED and "refused" in result.text
    assert desk.executions() == 0
    assert desk.status() is ProposalStatus.ESCALATED  # back with the person
    assert SqliteCaseStore(desk.conn).status(case_id) is CaseStatus.OPEN  # still to decide


def test_a_reviewer_cannot_approve_a_withdrawal_the_customer_never_confirmed(
    tmp_path: Path,
) -> None:
    # BH-B3-05: a go-ahead in the quoting turn on a human-tier quote opens a case before any yes.
    desk = Desk(tmp_path, [withdraw(40_000, yes=True)]).login("SPR-1004")
    r = desk.say("Withdraw $40,000. Go ahead.")
    assert r.outcome is Outcome.NEEDS_HUMAN and r.reference
    result = reviewer(desk).decide(decide(r.reference, Decision.APPROVE))
    assert result.outcome is Outcome.NOT_PERMITTED and "confirmation" in result.text
    assert desk.executions() == 0
    assert SqliteCaseStore(desk.conn).status(r.reference) is CaseStatus.OPEN


# ---------- the requests only a person decides ----------
FAQ = Citation(doc_id="faq", version=1, section="Waivers")
WAIVER_ANSWER = KnowledgeDraft(
    found=True,
    text="A terminal-illness waiver needs a physician's statement.",
    citations=(FAQ,),
)


FAQ_CHUNK = KnowledgeChunk(
    doc_id="faq",
    version=1,
    effective_date=date(2024, 1, 1),
    section="Waivers",
    text="A terminal-illness waiver needs a physician's statement.",
    source_path="knowledge/faq.md",
)


def request_desk(tmp_path: Path, kind: IntentKind, drafts: list[object]) -> Desk:
    desk = Desk(tmp_path, [Intent(kind=kind)], chunks=[FAQ_CHUNK], drafts=drafts)
    return desk.login("SPR-1001")


@pytest.mark.parametrize(
    ("kind", "reason", "looked_up"),
    [
        (IntentKind.HARDSHIP_WAIVER, CaseReason.WAIVER_REQUEST, True),  # FR-13, G-B4-03
        (IntentKind.RMD, CaseReason.RMD, True),  # FR-15, G-B4-05
        (IntentKind.FULL_SURRENDER, CaseReason.FULL_SURRENDER, False),  # NG-07, G-B4-04
    ],
)
def test_a_request_opens_a_case_and_moves_no_money(
    tmp_path: Path, kind: IntentKind, reason: CaseReason, looked_up: bool
) -> None:
    desk = request_desk(tmp_path, kind, [WAIVER_ANSWER] if looked_up else [])
    r = desk.say("I need help with my contract.")
    assert r.outcome is Outcome.NEEDS_HUMAN and r.reference
    assert Step.CREATE_CASE in r.steps and Step.EXECUTE not in r.steps
    assert (Step.SEARCH_KB in r.steps) is looked_up
    assert desk.executions() == 0
    if looked_up:
        assert r.citations == (FAQ,) and "physician" in r.reply_text
    assert "waived" not in r.reply_text.replace("nothing has been waived", "")  # NG-01
    desk_review = reviewer(desk)
    [row] = desk_review.queue(customer_id="SPR-1001")
    assert row.opened_for is reason and row.proposal_id is None
    result = desk_review.decide(decide(r.reference, Decision.APPROVE))
    assert result.outcome is Outcome.ANSWERED and desk.executions() == 0  # recorded only
    assert desk_review.queue(CaseStatus.APPROVED)[0].case_id == r.reference


# ---------- review defects on PR #150 ----------
def test_issue_151_a_reject_after_the_approval_is_refused(tmp_path: Path) -> None:
    # Issue #151, found by /code-review on PR #150: a reject was recorded on a withdrawal that had
    # already been approved or executed.
    desk, case_id = large_withdrawal_with_a_person(tmp_path)
    desk_review = reviewer(desk)
    proposal_id = desk.proposal_id()
    # Reviewer A's approval is recorded (the proposal is approved), then B rejects meanwhile.
    money = desk.stores.money
    assert money is not None
    from contracts.messages import Approval

    proposal = desk.stores.proposals.get(proposal_id)
    assert proposal is not None
    money.approvals.record(
        Approval(
            approval_id="appr-a",
            proposal_id=proposal_id,
            approver="human:a",
            decision=Decision.APPROVE,
            token_hmac=money.issue_token(proposal_id, proposal.hash),
        )
    )
    result = desk_review.decide(decide(case_id, Decision.REJECT, who="b"))
    assert result.outcome is Outcome.NOT_PERMITTED and "approved" in result.text
    assert SqliteCaseStore(desk.conn).status(case_id) is CaseStatus.OPEN  # nothing written
    assert desk.status() is ProposalStatus.APPROVED


@pytest.mark.parametrize("decision", [Decision.APPROVE, Decision.REJECT, Decision.REQUEST_INFO])
def test_issue_155_a_reviewer_id_outside_the_pattern_is_refused(
    tmp_path: Path, decision: Decision
) -> None:
    # Issue #155, found by /code-review on PR #150: "pat!" crashed reject and request_info.
    desk, case_id = large_withdrawal_with_a_person(tmp_path)
    with pytest.raises(ValueError, match="reviewer ID"):
        reviewer(desk).decide(decide(case_id, decision, who="pat!"))
    assert SqliteCaseStore(desk.conn).status(case_id) is CaseStatus.OPEN
    assert desk.status() is ProposalStatus.ESCALATED and desk.executions() == 0
