"""The identity table's only door (PG-04, ADR 0005).

Restricted values (date of birth, SSN digits) are compared and banded here and never returned:
`check_challenge` gives a boolean and `age_band` gives a band. No other module may name the
`identity` table or its columns (tested in data/tests/test_b2_store.py).
"""

import hmac
import sqlite3
from datetime import date

from contracts.messages import AgeBand


def _add_years(d: date, years: int, months: int = 0) -> date:
    total = d.month - 1 + months
    year, month = d.year + years + total // 12, total % 12 + 1
    try:
        return d.replace(year=year, month=month)
    except ValueError:  # day 29-31 missing in that month: use the 1st of the next (the later,
        # more cautious line: the IRS notice shows for one more day)
        return date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)


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
        stored = self._stored(customer_id)
        if stored is None:
            return False
        dob_ok = hmac.compare_digest(stored[0].encode(), dob.isoformat().encode())
        last4_ok = hmac.compare_digest(stored[1].encode(), last4.encode())
        return dob_ok and last4_ok

    def age_band(self, customer_id: str, as_of: date) -> AgeBand:
        """The band at `as_of` (59 and a half, and 80, are the IRS and vulnerability lines)."""
        stored = self._stored(customer_id)
        if stored is None:
            raise KeyError(customer_id)
        dob = date.fromisoformat(stored[0])
        if as_of < _add_years(dob, 59, 6):
            return AgeBand.UNDER_59_5
        if as_of < _add_years(dob, 80):
            return AgeBand.FROM_59_5_TO_79
        return AgeBand.EIGHTY_PLUS

    def store(self, customer_id: str, dob: date, last4: str) -> bool:
        """Insert the identity row if absent (used by the seed). True if a row was written."""
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO identity (customer_id, dob, ssn_last4) VALUES (?, ?, ?)",
            (customer_id, dob.isoformat(), last4),
        )
        return cur.rowcount == 1
