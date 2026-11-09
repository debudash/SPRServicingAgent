"""The business clock: every date comes from the configured as-of date, never from today."""

from datetime import date

from data.settings import load_settings


def as_of() -> date:
    """The configured as-of date (DESK_AS_OF, default 2024-12-01)."""
    raw = load_settings().as_of
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"DESK_AS_OF must be an ISO date (YYYY-MM-DD), got {raw!r}") from None


def _anniversary(start: date, year: int) -> date:
    try:
        return start.replace(year=year)
    except ValueError:  # 29 February start in a non-leap year
        return date(year, 2, 28)


def contract_year(start: date, as_of: date) -> int:
    """Year 1 until the first anniversary, then +1 at each anniversary (inclusive of the day)."""
    year = as_of.year - start.year
    if as_of < _anniversary(start, start.year + year):
        year -= 1
    return max(year, 0) + 1
