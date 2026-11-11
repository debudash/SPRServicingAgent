"""Contracts 0.6.2 (B4): the reviewer's port, case statuses and the remaining case reasons."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from contracts import CONTRACTS_VERSION
from contracts.messages import (
    CASE_DECIDABLE,
    DECISION_CASE_STATUS,
    REVIEWER_DECISIONS,
    CaseReason,
    CaseStatus,
    CaseSummary,
    Decision,
    ReviewResult,
)
from contracts.outcomes import Outcome
from contracts.ports import CaseReview, ReviewDesk


def test_version() -> None:
    assert CONTRACTS_VERSION == "0.6.3"  # 0.6.3 (#172) adds LoginDeskRunner.account


def test_the_case_statuses_match_the_store_column() -> None:
    # data/store/migrations/0002: CHECK (status IN ('open', 'info_requested', 'approved',
    # 'rejected', 'closed'))
    assert {s.value for s in CaseStatus} == {
        "open",
        "info_requested",
        "approved",
        "rejected",
        "closed",
    }


def test_every_reviewer_decision_moves_a_case() -> None:
    assert set(DECISION_CASE_STATUS) == REVIEWER_DECISIONS
    assert CASE_DECIDABLE == {CaseStatus.OPEN, CaseStatus.INFO_REQUESTED}
    # A decided case is final: approval and rejection are not decidable again.
    assert DECISION_CASE_STATUS[Decision.APPROVE] not in CASE_DECIDABLE
    assert DECISION_CASE_STATUS[Decision.REJECT] not in CASE_DECIDABLE


def test_the_b4_case_reasons() -> None:
    for reason in ("waiver_request", "hardship", "rmd", "full_surrender"):
        assert CaseReason(reason)


def test_only_an_approval_executes() -> None:
    ok = ReviewResult(
        case_id="CASE-1",
        decision=Decision.APPROVE,
        outcome=Outcome.EXECUTED,
        reference="TX-1",
        text="Executed.",
    )
    assert ok.reference == "TX-1"
    with pytest.raises(ValidationError):
        ReviewResult(
            case_id="CASE-1",
            decision=Decision.REJECT,
            outcome=Outcome.EXECUTED,
            reference="TX-1",
            text="Executed.",
        )


def test_a_case_summary() -> None:
    row = CaseSummary(
        case_id="CASE-1",
        customer_id="SPR-1004",
        opened_for=CaseReason.WITHDRAWAL_REVIEW,
        status=CaseStatus.OPEN,
        opened_at=datetime(2026, 11, 10, tzinfo=UTC),
        proposal_id="prop-1",
    )
    assert row.decided_by is None


def test_the_ports_name_their_methods() -> None:
    for name in ("get", "list_cases", "status", "decide"):
        assert hasattr(CaseReview, name)
    for name in ("queue", "case", "decide"):
        assert hasattr(ReviewDesk, name)
