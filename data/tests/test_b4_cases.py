"""B4: the case store's reviewer side (contracts 0.6.2 CaseReview, #145) and #144."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from contracts.messages import (
    CasePacket,
    CaseReason,
    CaseStatus,
    Decision,
    HumanDecision,
    Quote,
)
from contracts.ports import CaseReview, CaseStore
from data.identity import SqliteIdentityCheck
from data.store.accounts import SqliteAccountStore
from data.store.cases import SqliteCaseStore
from data.store.db import open_db
from data.store.quotes import SqliteQuoteService
from data.store.seed import seed_starter_kit

AS_OF = date(2024, 12, 1)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = open_db(tmp_path / "desk.db")
    seed_starter_kit(c)
    return c


def _quote(conn: sqlite3.Connection, customer_id: str, amount_cents: int) -> Quote:
    q = SqliteQuoteService(SqliteAccountStore(conn, SqliteIdentityCheck(conn))).quote(
        customer_id, amount_cents, AS_OF
    )
    assert isinstance(q, Quote)
    return q


def review_packet(conn: sqlite3.Connection, case_id: str = "CASE-R1") -> CasePacket:
    return CasePacket(
        case_id=case_id,
        conversation_id="CV-R",
        customer_id="SPR-1004",
        opened_for=CaseReason.WITHDRAWAL_REVIEW,
        request_summary="A withdrawal over $25,000.",
        quote=_quote(conn, "SPR-1004", 3_000_000),
        excerpt="I want to withdraw $30,000.",
        recommendation="Review the proposal and its quote.",
        proposal_id="prop-review-1",
    )


def plain_packet(case_id: str, customer_id: str = "SPR-1003") -> CasePacket:
    return CasePacket(
        case_id=case_id,
        conversation_id=f"CV-{case_id}",
        customer_id=customer_id,
        opened_for=CaseReason.FULL_SURRENDER,
        request_summary="Asked to surrender the whole contract.",
        quote=None,
        excerpt="Close it out.",
        recommendation="Contact the customer.",
    )


def decide(case_id: str, decision: Decision, reviewer: str = "pat") -> HumanDecision:
    return HumanDecision(case_id=case_id, reviewer_id=reviewer, decision=decision)


# ---------- #144 ----------
def test_issue_144_the_case_row_keeps_the_proposal_id(conn: sqlite3.Connection) -> None:
    # Issue #144, found while building B4: the INSERT hard-coded NULL for proposal_id.
    SqliteCaseStore(conn).open(review_packet(conn))
    (stored,) = conn.execute("SELECT proposal_id FROM cases WHERE case_id = 'CASE-R1'").fetchone()
    assert stored == "prop-review-1"


# ---------- #145: CaseReview ----------
def test_the_store_conforms_to_both_case_ports(conn: sqlite3.Connection) -> None:
    store = SqliteCaseStore(conn)
    opened: CaseStore = store
    review: CaseReview = store
    assert callable(opened.open) and callable(review.decide)


def test_list_cases_oldest_first_with_filters(conn: sqlite3.Connection) -> None:
    store = SqliteCaseStore(conn)
    store.open(review_packet(conn))
    store.open(plain_packet("CASE-2"))
    store.open(plain_packet("CASE-3", customer_id="SPR-1001"))
    store.decide(decide("CASE-2", Decision.REJECT))
    rows = store.list_cases()
    assert [r.case_id for r in rows] == ["CASE-R1", "CASE-2", "CASE-3"]
    assert rows[0].proposal_id == "prop-review-1" and rows[0].customer_id == "SPR-1004"
    assert rows[0].opened_for is CaseReason.WITHDRAWAL_REVIEW
    assert rows[0].opened_at.tzinfo is not None
    assert [r.case_id for r in store.list_cases(CaseStatus.OPEN)] == ["CASE-R1", "CASE-3"]
    assert [r.case_id for r in store.list_cases(customer_id="SPR-1001")] == ["CASE-3"]
    rejected = store.list_cases(CaseStatus.REJECTED)
    assert [(r.case_id, r.decided_by) for r in rejected] == [("CASE-2", "human:pat")]


@pytest.mark.parametrize(
    ("decision", "status"),
    [
        (Decision.APPROVE, CaseStatus.APPROVED),
        (Decision.REJECT, CaseStatus.REJECTED),
        (Decision.REQUEST_INFO, CaseStatus.INFO_REQUESTED),
    ],
)
def test_decide_moves_the_case(
    conn: sqlite3.Connection, decision: Decision, status: CaseStatus
) -> None:
    store = SqliteCaseStore(conn)
    store.open(plain_packet("CASE-2"))
    store.decide(decide("CASE-2", decision))
    assert store.status("CASE-2") is status
    by, at = conn.execute(
        "SELECT decided_by, decided_at FROM cases WHERE case_id = 'CASE-2'"
    ).fetchone()
    assert by == "human:pat" and at


def test_a_case_waiting_on_information_can_still_be_decided(conn: sqlite3.Connection) -> None:
    store = SqliteCaseStore(conn)
    store.open(plain_packet("CASE-2"))
    store.decide(decide("CASE-2", Decision.REQUEST_INFO))
    store.decide(decide("CASE-2", Decision.APPROVE, reviewer="sam"))
    assert store.status("CASE-2") is CaseStatus.APPROVED
    assert store.list_cases()[0].decided_by == "human:sam"


@pytest.mark.parametrize("first", [Decision.APPROVE, Decision.REJECT])
def test_a_decided_case_is_final(conn: sqlite3.Connection, first: Decision) -> None:
    store = SqliteCaseStore(conn)
    store.open(plain_packet("CASE-2"))
    store.decide(decide("CASE-2", first))
    before = store.list_cases()[0]
    with pytest.raises(ValueError):
        store.decide(decide("CASE-2", Decision.APPROVE, reviewer="sam"))
    assert store.list_cases()[0] == before  # nothing written


def test_unknown_cases_raise_key_error(conn: sqlite3.Connection) -> None:
    store = SqliteCaseStore(conn)
    with pytest.raises(KeyError):
        store.status("CASE-404")
    with pytest.raises(KeyError):
        store.decide(decide("CASE-404", Decision.APPROVE))
