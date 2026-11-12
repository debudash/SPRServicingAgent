"""The amount guard (issue #191): a quoted amount is one the customer typed, not a model's guess.

The Concierge reads the amount out of the customer's message. Live, with a quote in context, it
turned "5000" into 450000 cents ($4,500), and the desk quoted an amount nobody asked for. Numbers
come from code, not a model (GR-02), so code reads the amounts the customer actually wrote and
holds the model's reading against them.

Only amount-shaped numbers count: a dollar sign, thousands commas, a multiplier (k, thousand,
grand, million) or at least three digits. Ages, contract years, percentages, IDs, masked
credentials ([SSN-4]), dates, negatives and malformed numbers are not amounts (review on PR #192).
"""

import re
from decimal import Decimal

from contracts.messages import Intent

_NUMBER = re.compile(
    r"(\$\s?)?(\d+(?:,\d+)*)(?:\.(\d+))?\s?(k|thousand|grand|million)?\b", re.IGNORECASE
)
_MULTIPLIER = {"k": 1_000, "thousand": 1_000, "grand": 1_000, "million": 1_000_000}
_NOT_BEFORE = set("-[/.,") | {"_"}
_NOT_AFTER = set("%/-")
_NOT_AFTER_WORDS = ("percent", "year", "years", "yr", "yrs")
_NOT_BEFORE_WORDS = ("year", "age", "aged", "turned")
_COMMAS = re.compile(r"\d{1,3}(,\d{3})+")


def _amount(m: re.Match[str], text: str) -> int | None:
    """The match as cents, or None when it isn't an amount the customer wrote."""
    dollar, whole, decimals, multiplier = m.groups()
    start, end = m.start(), m.end()
    before, after = text[start - 1 : start], text[end : end + 1]
    if before.isalnum() or before in _NOT_BEFORE:  # part of an ID, a date, a mask or a negative
        return None
    if after in _NOT_AFTER or (after in ".," and text[end + 1 : end + 2].isdigit()):
        return None
    if text[end:].lstrip().lower().startswith(_NOT_AFTER_WORDS):
        return None
    words = text[:start].lower().split()
    if words and words[-1].strip(",") in _NOT_BEFORE_WORDS:
        return None
    if "," in whole and not _COMMAS.fullmatch(whole):  # "1,00", "1,5000"
        return None
    if decimals is not None and len(decimals) > 2:  # "5000.123"
        return None
    if not (dollar or "," in whole or multiplier or len(whole) >= 3):  # "67", "3": not money
        return None
    value = Decimal(whole.replace(",", "") + "." + (decimals or "0"))
    if multiplier:
        value *= _MULTIPLIER[multiplier.lower()]
    cents = value * 100
    return int(cents) if cents == cents.to_integral_value() and cents > 0 else None


def amounts_in(text: str) -> set[int]:
    """Every amount the customer wrote with digits, in cents."""
    return {c for m in _NUMBER.finditer(text) if (c := _amount(m, text)) is not None}


def checked_amount(intent: Intent, text: str) -> Intent:
    """Issue #191: keep the model's amount only when the customer typed it.

    Kept when it is among the amounts typed, or when none were typed with digits ("five
    thousand", "yes"). Replaced when the whole message is one amount ("5000"): that is the
    customer's own number. Otherwise dropped, so a confirm stays a plain confirm and a request
    gets "How much would you like to withdraw?" rather than a quote for a guessed amount.
    """
    typed = amounts_in(text)
    if intent.amount_cents is None or not typed or intent.amount_cents in typed:
        return intent
    bare = _NUMBER.fullmatch(text.strip(" .!?"))
    if bare is not None and len(typed) == 1:
        return intent.model_copy(update={"amount_cents": next(iter(typed))})
    return intent.model_copy(update={"amount_cents": None})
