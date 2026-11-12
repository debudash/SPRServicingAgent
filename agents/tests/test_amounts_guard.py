"""The amount guard (#191): the quoted amount is one the customer typed, never the model's guess."""

import pytest

from agents.guards.amounts import amounts_in, checked_amount
from contracts.messages import Intent, IntentKind


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("5000", {500_000}),
        ("withdraw $5,000.00 please", {500_000}),
        ("26,000", {2_600_000}),
        ("$1,234.5", {123_450}),
        ("10k", {1_000_000}),
        ("10 thousand", {1_000_000}),
        ("1.5 million", {150_000_000}),
        ("5 grand", {500_000}),
        ("5000 or 6000", {500_000, 600_000}),
        # Not amounts (review on PR #192): words only, ages, years, percentages, IDs, masks,
        # dates, negatives, and malformed numbers.
        ("five thousand", set()),
        ("I am 67", set()),
        ("contract year 3", set()),
        ("in year 2024", set()),
        ("25% or 10 percent", set()),
        ("SPR-1001", set()),
        ("[SSN-4] and [DOB]", set()),
        ("12/31/1990", set()),
        ("-5000", set()),
        ("5000.123", set()),
        ("1,00", set()),
    ],
)
def test_issue_191_amounts_are_read_from_the_text(text: str, cents: set[int]) -> None:
    """#191, found checking #187 live; cases from the two-axis review of PR #192."""
    assert amounts_in(text) == cents


def _w(cents: int | None) -> Intent:
    return Intent(kind=IntentKind.WITHDRAWAL, amount_cents=cents)


@pytest.mark.parametrize(
    ("model", "text", "kept"),
    [
        (450_000, "5000", 500_000),  # the live bug: a bare amount is the customer's own
        (500_000, "I'm 72 and need 5000", 500_000),  # the model's amount was typed: kept
        (500_000, "I'm 67, withdraw five thousand", 500_000),  # no amount digits: kept
        (1_000_000, "10 thousand", 1_000_000),
        (450_000, "withdraw 5000 please", None),  # not typed, not a bare amount: ask again
        (450_000, "5000 or 6000", None),
        (None, "hello", None),
    ],
)
def test_issue_191_the_model_amount_is_kept_only_if_typed(
    model: int | None, text: str, kept: int | None
) -> None:
    assert checked_amount(_w(model), text).amount_cents == kept


def test_issue_191_a_confirm_mentioning_an_age_stays_a_confirm() -> None:
    """Review on PR #192 (spec): "yes, I'm 72" on a $26,000 quote must not become a $72 quote."""
    yes = Intent(kind=IntentKind.CONFIRM, amount_cents=2_600_000, explicit_yes=True)
    checked = checked_amount(yes, "yes, I'm 72")
    assert checked.kind is IntentKind.CONFIRM and checked.amount_cents == 2_600_000
