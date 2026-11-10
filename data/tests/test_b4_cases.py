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
    (stored,) = conn.execute(
        "SELECT proposal_id FROM cases WHERE case_id = 'CASE-R1'"
    ).fetchone()
    assert stored == "prop-review-1"
