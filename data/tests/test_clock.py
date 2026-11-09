"""Issue #34: settings and the as-of clock."""

from datetime import date
from pathlib import Path

import pytest

from data.clock import as_of, contract_year
from data.settings import load_settings

AS_OF = date(2024, 12, 1)


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (date(2022, 6, 1), 3),  # SPR-1001
        (date(2023, 1, 15), 2),  # SPR-1002
        (date(2021, 9, 1), 4),  # SPR-1003
        (date(2020, 3, 10), 5),  # SPR-1004
    ],
)
def test_starter_accounts(start: date, expected: int) -> None:
    assert contract_year(start, AS_OF) == expected


def test_anniversary_edges() -> None:
    start = date(2022, 6, 1)
    assert contract_year(start, start) == 1
    assert contract_year(start, date(2023, 5, 31)) == 1
    assert contract_year(start, date(2023, 6, 1)) == 2
    assert contract_year(start, date(2023, 6, 2)) == 2


def test_leap_day_start() -> None:
    start = date(2020, 2, 29)
    assert contract_year(start, date(2021, 2, 27)) == 1
    assert contract_year(start, date(2021, 2, 28)) == 2
    assert contract_year(start, date(2024, 2, 28)) == 4
    assert contract_year(start, date(2024, 2, 29)) == 5


def test_as_of_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DESK_AS_OF", raising=False)
    assert as_of() == AS_OF


def test_as_of_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DESK_AS_OF", "2025-03-04")
    assert as_of() == date(2025, 3, 4)


def test_as_of_rejects_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DESK_AS_OF", "next tuesday")
    with pytest.raises(ValueError, match="DESK_AS_OF"):
        as_of()


def test_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DESK_VAR_DIR", raising=False)
    s = load_settings()
    assert s.desk_db == Path("var/desk.db")
    assert s.checkpoints_db == Path("var/checkpoints.db")
    assert s.chroma_dir == Path("var/chroma")
    monkeypatch.setenv("DESK_VAR_DIR", "/tmp/x")
    assert load_settings().desk_db == Path("/tmp/x/desk.db")
