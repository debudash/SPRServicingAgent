"""The business clock: every date comes from the configured as-of date, never from today."""

import calendar
from datetime import date

from data.settings import load_settings


def as_of() -> date:
    """The configured as-of date (DESK_AS_OF, default 2024-12-01)."""
    raw = load_settings().as_of
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"DESK_AS_OF must be an ISO date (YYYY-MM-DD), got {raw!r}") from None


def add_months(d: date, months: int) -> date:
    """`d` moved by whole months. A day the target month lacks (29 February in a common year,
    31 August + 6 months) becomes that month's last day: the one rule for every anniversary,
    contract years and age lines alike."""
    total = d.month - 1 + months
    year, month = d.year + total // 12, total % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _anniversary(start: date, year: int) -> date:
    return add_months(start, 12 * (year - start.year))


def contract_year(start: date, as_of: date) -> int:
    """Year 1 until the first anniversary, then +1 at each anniversary (inclusive of the day)."""
    year = as_of.year - start.year
    if as_of < _anniversary(start, start.year + year):
        year -= 1
    return max(year, 0) + 1
