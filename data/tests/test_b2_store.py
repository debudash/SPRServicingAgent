"""Issue #57: identity store split, starter-kit seed, account view and case store."""

import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from contracts.messages import AccountStatus, AgeBand, CasePacket, CaseReason
from contracts.ports import AccountStore, CaseStore, IdentityCheck
from data.identity import SqliteIdentityCheck
from data.store.accounts import SqliteAccountStore
from data.store.cases import SqliteCaseStore
from data.store.db import open_db
from data.store.seed import seed_starter_kit

AS_OF = date(2024, 12, 1)
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = open_db(tmp_path / "desk.db")
    seed_starter_kit(c)
    return c


def _stores(conn: sqlite3.Connection) -> tuple[SqliteAccountStore, SqliteIdentityCheck]:
    identity = SqliteIdentityCheck(conn)
    return SqliteAccountStore(conn, identity), identity


def _withdrawal(conn: sqlite3.Connection, tid: str, year: int, gross: int, as_of: str) -> None:
    conn.execute(
        "INSERT INTO transactions (transaction_id, customer_id, proposal_id, contract_year, "
        "gross_cents, free_cents, excess_cents, charge_cents, net_cents, approved_by, "
        "executed_as_of, is_synthetic) "
        "VALUES (?, 'SPR-1001', NULL, ?, ?, ?, 0, 0, ?, 'seed', ?, 1)",
        (tid, year, gross, gross, gross, as_of),
    )


# ---------- seed ----------
def test_seed_loads_the_starter_kit_once(conn: sqlite3.Connection) -> None:
    assert seed_starter_kit(conn) == 0  # second run inserts nothing
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM beneficiaries").fetchone()[0] >= 4
    row = conn.execute(
        "SELECT balance_cents, gate_a_trusted, is_synthetic FROM accounts "
        "WHERE customer_id = 'SPR-1001'"
    ).fetchone()
    assert row == (8_745_062, 1, 0)


def test_stored_contract_year_matches_the_derived_one(conn: sqlite3.Connection) -> None:
    # PG-02: the stored year is kept only to check it against the as-of clock.
    accounts, _ = _stores(conn)
    for customer_id, stored in conn.execute(
        "SELECT customer_id, contract_year_stored FROM accounts"
    ).fetchall():
        assert accounts.view(customer_id, AS_OF).contract_year == stored, customer_id


# ---------- Gate A ----------
def test_gate_a_follows_identity_verified(conn: sqlite3.Connection) -> None:
    accounts, _ = _stores(conn)
    assert accounts.gate_a("SPR-1001")
    assert not accounts.gate_a("SPR-1002")
    assert not accounts.gate_a("SPR-9999")  # unknown customer


# ---------- Gate B ----------
def test_check_challenge_needs_both_values(conn: sqlite3.Connection) -> None:
    _, identity = _stores(conn)
    assert identity.check_challenge("SPR-1001", date(1958, 3, 14), "7823")
    assert not identity.check_challenge("SPR-1001", date(1958, 3, 15), "7823")
    assert not identity.check_challenge("SPR-1001", date(1958, 3, 14), "7832")
    assert not identity.check_challenge("SPR-9999", date(1958, 3, 14), "7823")


def test_correct_credentials_still_check_on_an_untrusted_account(
    conn: sqlite3.Connection,
) -> None:
    # Gate B is only a match; refusing untrusted accounts is Gate A's job (FR-02, FR-03).
    _, identity = _stores(conn)
    row = conn.execute("SELECT dob, ssn_last4 FROM identity WHERE customer_id='SPR-1002'")
    dob, last4 = row.fetchone()
    assert identity.check_challenge("SPR-1002", date.fromisoformat(dob), last4)


@pytest.mark.parametrize(
    ("as_of", "band"),
    [
        (date(2017, 9, 13), AgeBand.UNDER_59_5),  # 59 and 6 months, less a day
        (date(2017, 9, 14), AgeBand.FROM_59_5_TO_79),  # 59 and 6 months
        (date(2038, 3, 13), AgeBand.FROM_59_5_TO_79),
        (date(2038, 3, 14), AgeBand.EIGHTY_PLUS),  # 80th birthday
    ],
)
def test_age_band_boundaries(conn: sqlite3.Connection, as_of: date, band: AgeBand) -> None:
    _, identity = _stores(conn)  # SPR-1001 was born 1958-03-14
    assert identity.age_band("SPR-1001", as_of) is band


# ---------- account view (D-05) ----------
def test_account_view_for_spr_1001(conn: sqlite3.Connection) -> None:
    accounts, _ = _stores(conn)
    view = accounts.view("SPR-1001", AS_OF)
    assert view.balance_cents == 8_745_062
    assert view.contract_year == 3
    assert view.allowance_remaining_cents == 874_506  # 10% of $87,450.62, half-up
    assert view.age_band is AgeBand.FROM_59_5_TO_79
    assert view.account_status is AccountStatus.ACTIVE
    assert view.withdrawals_this_year == 0


def test_withdrawals_this_contract_year_reduce_the_allowance(conn: sqlite3.Connection) -> None:
    _withdrawal(conn, "T1", 3, 500_000, "2024-07-01")
    _withdrawal(conn, "T0", 2, 900_000, "2023-07-01")
    view = SqliteAccountStore(conn, SqliteIdentityCheck(conn)).view("SPR-1001", AS_OF)
    assert view.withdrawals_this_year == 1
    assert view.allowance_remaining_cents == 374_506  # last year's withdrawal does not count


def test_allowance_never_goes_below_zero(conn: sqlite3.Connection) -> None:
    _withdrawal(conn, "T1", 3, 2_000_000, "2024-07-01")
    view = SqliteAccountStore(conn, SqliteIdentityCheck(conn)).view("SPR-1001", AS_OF)
    assert view.allowance_remaining_cents == 0


def test_view_of_an_unknown_customer_raises_key_error(conn: sqlite3.Connection) -> None:
    accounts, _ = _stores(conn)
    with pytest.raises(KeyError):
        accounts.view("SPR-9999", AS_OF)


# ---------- cases ----------
def _packet(case_id: str = "CASE-1") -> CasePacket:
    return CasePacket(
        case_id=case_id,
        conversation_id="CV1",
        customer_id="SPR-1003",
        opened_for=CaseReason.THIRD_PARTY,
        request_summary="A family member asked to withdraw for the customer.",
        quote=None,
        excerpt="I'm Linda's son and I handle her finances.",
        recommendation="Contact the owner through a verified channel.",
    )


def test_case_store_round_trips_a_packet(conn: sqlite3.Connection) -> None:
    cases = SqliteCaseStore(conn)
    cases.open(_packet())
    assert cases.get("CASE-1") == _packet()
    assert cases.get("CASE-404") is None
    status, opened_for = conn.execute(
        "SELECT status, opened_for FROM cases WHERE case_id = 'CASE-1'"
    ).fetchone()
    assert (status, opened_for) == ("open", "third_party")


def test_a_duplicate_case_id_raises(conn: sqlite3.Connection) -> None:
    cases = SqliteCaseStore(conn)
    cases.open(_packet())
    with pytest.raises(sqlite3.IntegrityError):
        cases.open(_packet())


def test_stores_conform_to_the_ports(conn: sqlite3.Connection) -> None:
    accounts, identity = _stores(conn)
    a: AccountStore = accounts
    i: IdentityCheck = identity
    c: CaseStore = SqliteCaseStore(conn)
    assert a.gate_a("SPR-1001") and not i.check_challenge("SPR-1001", AS_OF, "0000")
    c.open(_packet("CASE-9"))
    assert SqliteCaseStore(conn).get("CASE-9") == _packet("CASE-9")


# ---------- the identity table is reachable only through data/identity.py (PG-04) ----------
# Issue #66 (found by /code-review on PR #63): `dob` was not covered, so SQL reading the column
# (or a comma join on identity) passed. `dob` is flagged only inside SQL (a line with a SQL
# keyword before it), because the word is common in non-SQL code such as the credential masks.
_FORBIDDEN = re.compile(
    r"ssn_last4"
    r"|\b(FROM|INTO|JOIN|UPDATE)\s+identity\b"
    r"|\bFROM\s+\w+(\s+\w+)?\s*,\s*identity\b"
    r"|\b(SELECT|WHERE|SET|INSERT|UPDATE)\b[^\n#]*\bdob\b",
    re.IGNORECASE,
)
_ALLOWED = {REPO / "data" / "identity.py"}


def test_only_data_identity_touches_the_identity_table() -> None:
    scanned = 0
    for lane in ("data", "agents"):
        for path in (REPO / lane).rglob("*.py"):
            if path in _ALLOWED or "tests" in path.parts:
                continue
            scanned += 1
            assert not _FORBIDDEN.search(path.read_text(encoding="utf-8")), path
    assert scanned >= 15  # the scan found the lanes' modules, not an empty tree


# ---------- #65: a malformed stored DOB was quoted in the exception message ----------
# Found by /code-review on PR #63 (standards): the runner logs exceptions, so the value would leak.
def _chain_text(exc: BaseException) -> str:
    parts: list[str] = []
    e: BaseException | None = exc
    while e is not None:
        parts.append(repr(e))
        e = e.__cause__ or (None if e.__suppress_context__ else e.__context__)
    return " ".join(parts)


def test_issue_65_a_malformed_stored_dob_is_not_in_the_error(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE identity SET dob = '19X8-03-14' WHERE customer_id = 'SPR-1001'")
    with pytest.raises(ValueError) as info:
        SqliteIdentityCheck(conn).age_band("SPR-1001", AS_OF)
    assert "19X8" not in _chain_text(info.value)
    assert "SPR-1001" in str(info.value)


def test_issue_65_a_malformed_seed_dob_is_not_in_the_error(tmp_path: Path) -> None:
    kit = tmp_path / "accounts.json"
    original = (REPO / "problemstmt/spr_starter_kit/data/accounts.json").read_text("utf-8")
    kit.write_text(original.replace('"1958-03-14"', '"14th of March 58"'), encoding="utf-8")
    c = open_db(tmp_path / "bad.db")
    with pytest.raises(ValueError) as info:
        seed_starter_kit(c, kit)
    assert "March 58" not in _chain_text(info.value)
    assert c.execute("SELECT COUNT(*) FROM accounts WHERE customer_id='SPR-1001'").fetchone() == (
        0,
    )


# ---------- #66: the isolation test let SQL read the dob column ----------
# Found by /code-review on PR #63 (spec).
@pytest.mark.parametrize(
    "source",
    [
        '"SELECT dob FROM accounts a, identity i WHERE a.customer_id = i.customer_id"',
        '"SELECT name, dob FROM people"',
        "'UPDATE accounts SET dob = ?'",
        '"SELECT * FROM accounts, identity"',
    ],
)
def test_issue_66_sql_naming_dob_or_joining_identity_is_flagged(source: str) -> None:
    assert _FORBIDDEN.search(source)


@pytest.mark.parametrize(
    "source",
    ['DOB_MASK = "[DOB]"', 'dob = date.fromisoformat(a["dob"])', "# the customer's dob"],
)
def test_issue_66_non_sql_mentions_of_dob_are_allowed(source: str) -> None:
    assert not _FORBIDDEN.search(source)


# ---------- one leap-day rule for anniversaries and age lines (review on PR #63) ----------
@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(1960, 2, 29), 12, date(1961, 2, 28)),  # missing day: the month's last day
        (date(1965, 8, 31), 59 * 12 + 6, date(2025, 2, 28)),
        (date(1964, 8, 31), 59 * 12 + 6, date(2024, 2, 29)),
        (date(1958, 3, 14), 59 * 12 + 6, date(2017, 9, 14)),
    ],
)
def test_add_months_uses_the_last_day_for_a_missing_day(
    start: date, months: int, expected: date
) -> None:
    from data.clock import add_months

    assert add_months(start, months) == expected
