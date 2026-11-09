"""The identity table's only door (PG-04, ADR 0005).

Restricted values (date of birth, SSN digits) are compared and banded here and never returned:
`check_challenge` gives a boolean and `age_band` gives a band. No other module may name the
`identity` table or its columns (tested in data/tests/test_b2_store.py).
"""

import hmac
import sqlite3
from datetime import date

from contracts.messages import AgeBand
from data.clock import add_months


def parse_dob(customer_id: str, raw: str) -> date:
    """Parse a stored or seeded date of birth without ever quoting it.

    Issue #65 (found by /code-review on PR #63): `date.fromisoformat` puts the bad input in its
    message, and the runner logs exceptions, so a malformed DOB would leak into logs (FR-23).
    Re-raising `from None` with only the customer ID keeps the value out of the message and chain.
    """
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        raise ValueError(f"malformed date of birth for {customer_id}") from None


class SqliteIdentityCheck:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _stored(self, customer_id: str) -> tuple[str, str] | None:
        row = self._conn.execute(
            "SELECT dob, ssn_last4 FROM identity WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        return None if row is None else (str(row[0]), str(row[1]))

    def check_challenge(self, customer_id: str, dob: date, last4: str) -> bool:
        """Gate B. Both values are compared in constant time, and both always are."""
        # An unknown customer is compared against a placeholder that matches nothing, so the
        # timing does not say whether the customer exists (review on PR #63).
        row = self._stored(customer_id)
        stored = row or ("not-a-date", "none")
        dob_ok = hmac.compare_digest(stored[0].encode(), dob.isoformat().encode())
        last4_ok = hmac.compare_digest(stored[1].encode(), last4.encode())
        return row is not None and dob_ok and last4_ok

    def age_band(self, customer_id: str, as_of: date) -> AgeBand:
        """The band at `as_of` (59 and a half, and 80, are the IRS and vulnerability lines)."""
        stored = self._stored(customer_id)
        if stored is None:
            raise KeyError(customer_id)
        dob = parse_dob(customer_id, stored[0])
        if as_of < add_months(dob, 59 * 12 + 6):
            return AgeBand.UNDER_59_5
        if as_of < add_months(dob, 80 * 12):
            return AgeBand.FROM_59_5_TO_79
        return AgeBand.EIGHTY_PLUS

    def store(self, customer_id: str, dob: str, last4: str) -> bool:
        """Insert the identity row if absent (used by the seed). True if a row was written."""
        parsed = parse_dob(customer_id, dob)
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO identity (customer_id, dob, ssn_last4) VALUES (?, ?, ?)",
            (customer_id, parsed.isoformat(), last4),
        )
        return cur.rowcount == 1
