"""Issue #101 (ADR 0007): the logins table, password hashes and the demo passwords."""

import json
import sqlite3
from pathlib import Path

import pytest

from contracts.ports import PasswordCheck
from data.identity import SqliteIdentityCheck
from data.store.db import open_db
from data.store.seed import DEMO_LOGINS, seed_demo_logins, seed_starter_kit
from data.tests.isolation import RESTRICTED, SCANNED_LANES, forbidden_sql, violations


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = open_db(tmp_path / "desk.db")
    seed_starter_kit(c)
    return c


def _demo() -> dict[str, str]:
    data = json.loads(DEMO_LOGINS.read_text(encoding="utf-8"))
    assert data["synthetic"] is True  # labelled: these are demo values, not real credentials
    passwords: dict[str, str] = data["passwords"]
    return passwords


def test_every_starter_customer_has_a_demo_password() -> None:
    assert set(_demo()) == {"SPR-1001", "SPR-1002", "SPR-1003", "SPR-1004"}


def test_the_seed_stores_hashes_never_passwords(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT customer_id, password_hash, salt FROM logins").fetchall()
    assert len(rows) == 4
    stored = " ".join(f"{h} {s}" for _, h, s in rows)
    for password in _demo().values():
        assert password not in stored


def test_the_seed_runs_once(conn: sqlite3.Connection) -> None:
    before = conn.execute("SELECT password_hash FROM logins ORDER BY customer_id").fetchall()
    assert seed_demo_logins(conn) == 0
    after = conn.execute("SELECT password_hash FROM logins ORDER BY customer_id").fetchall()
    assert before == after


def test_the_right_password_passes(conn: sqlite3.Connection) -> None:
    check: PasswordCheck = SqliteIdentityCheck(conn)
    for customer_id, password in _demo().items():
        assert check.check_password(customer_id, password), customer_id


@pytest.mark.parametrize(
    ("customer_id", "password"),
    [
        ("SPR-1001", "wrong"),
        ("SPR-1001", ""),
        ("SPR-9999", "anything"),  # unknown customer: the same answer as a wrong password
    ],
)
def test_anything_else_fails(conn: sqlite3.Connection, customer_id: str, password: str) -> None:
    assert not SqliteIdentityCheck(conn).check_password(customer_id, password)


def test_another_customers_password_fails(conn: sqlite3.Connection) -> None:
    demo = _demo()
    assert not SqliteIdentityCheck(conn).check_password("SPR-1001", demo["SPR-1003"])


def test_equal_passwords_get_different_hashes(conn: sqlite3.Connection) -> None:
    identity = SqliteIdentityCheck(conn)
    conn.execute("DELETE FROM logins WHERE customer_id IN ('SPR-1001', 'SPR-1003')")
    identity.store_password("SPR-1001", "same-password")
    identity.store_password("SPR-1003", "same-password")
    hashes = conn.execute(
        "SELECT password_hash FROM logins WHERE customer_id IN ('SPR-1001', 'SPR-1003')"
    ).fetchall()
    assert hashes[0] != hashes[1]  # a per-customer salt
    assert identity.check_password("SPR-1001", "same-password")


def test_the_identity_check_never_shows_a_hash(conn: sqlite3.Connection) -> None:
    identity = SqliteIdentityCheck(conn)
    shown = repr(identity) + str(vars(identity).keys())
    assert "password_hash" not in shown and "salt" not in shown


# ---------- the logins table is reachable only through data/identity.py (PG-04, ADR 0007) ----
# The scan itself is shared with the identity table (data/tests/isolation.py, issue #111).
def test_only_data_identity_touches_the_logins_table() -> None:
    found, scanned = violations()
    assert found == []
    assert scanned >= 15


@pytest.mark.parametrize(
    "source", ['"SELECT password_hash FROM x"', '"INSERT INTO logins VALUES (?)"']
)
def test_the_logins_scan_catches_direct_sql(source: str) -> None:
    assert forbidden_sql(source)


# ---------- #111: the isolation scans missed quoted, prefixed, joined and DDL forms ----------
# Found by /code-review on PR #109 (both axes): PG-04 rests on these scans alone.

_MISSED_FORMS = [
    'FROM "{t}"',
    "FROM `{t}`",
    "FROM [{t}]",
    "FROM main.{t}",
    'FROM main."{t}"',
    "SELECT * FROM accounts, {t}",
    "SELECT * FROM accounts a, {t} i",
    "DROP TABLE {t}",
    "ALTER TABLE {t} ADD x",
    "CREATE TABLE IF NOT EXISTS {t} (x)",
    "PRAGMA table_info({t})",
    "INSERT INTO {t} VALUES (?)",
    "DELETE FROM {t}",
    "x JOIN {t} ON 1",
]


@pytest.mark.parametrize("table", sorted(RESTRICTED))
@pytest.mark.parametrize("form", _MISSED_FORMS)
def test_issue_111_every_sql_form_naming_a_restricted_table_is_caught(
    table: str, form: str
) -> None:
    assert forbidden_sql(form.format(t=table)), form.format(t=table)


@pytest.mark.parametrize(
    "source",
    [
        '"SELECT salt FROM x"',
        '"SELECT dob FROM x"',
        '"UPDATE x SET password_hash = ?"',
        "ssn_last4",
    ],
)
def test_issue_111_restricted_columns_are_caught(source: str) -> None:
    assert forbidden_sql(source)


@pytest.mark.parametrize(
    "source",
    [
        "accounts=SqliteAccountStore(conn, identity),",
        "def f(conn, identity): ...",
        "identity = SqliteIdentityCheck(conn)",
        "# seed the demo logins once",
        'DOB_MASK = "[DOB]"',
        "salt = secrets.token_hex(16)",
        "from data.identity import SqliteIdentityCheck",
    ],
)
def test_issue_111_ordinary_python_is_not_flagged(source: str) -> None:
    assert not forbidden_sql(source)


def test_issue_111_every_python_lane_is_scanned() -> None:
    assert {"data", "agents", "evals", "redteam"} <= set(SCANNED_LANES)


# ---------- #112: check_password raised on a corrupt login row ----------
# Found by /code-review on PR #109 (spec): PasswordCheck promises a boolean; a guard fails closed.
@pytest.mark.parametrize(
    "corrupt",
    [
        "UPDATE logins SET salt = 'not-hex' WHERE customer_id = 'SPR-1001'",
        "UPDATE logins SET scrypt_n = 3 WHERE customer_id = 'SPR-1001'",  # not a power of 2
        "UPDATE logins SET scrypt_r = 0 WHERE customer_id = 'SPR-1001'",
    ],
)
def test_issue_112_a_corrupt_login_row_refuses_instead_of_raising(
    conn: sqlite3.Connection, corrupt: str
) -> None:
    conn.execute(corrupt)
    assert SqliteIdentityCheck(conn).check_password("SPR-1001", _demo()["SPR-1001"]) is False
