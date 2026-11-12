"""Gate A and the model-safe account view (FR-02, FR-03, D-05, PG-04)."""

import sqlite3
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from contracts.messages import AccountStatus, AccountView
from data.clock import contract_year
from data.identity import SqliteIdentityCheck

FREE_WITHDRAWAL_RATE = Decimal("0.10")  # D-05: 10% of the balance per contract year


def free_allowance_cents(balance_cents: int, withdrawn_this_year_cents: int) -> int:
    """D-05: 10% of the balance, half-up to the cent, less this contract year's withdrawals."""
    ten_percent = int(
        (Decimal(balance_cents) * FREE_WITHDRAWAL_RATE).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )
    return max(ten_percent - withdrawn_this_year_cents, 0)


class SqliteAccountStore:
    def __init__(self, conn: sqlite3.Connection, identity: SqliteIdentityCheck) -> None:
        self._conn = conn
        self._identity = identity

    def gate_a(self, customer_id: str) -> bool:
        row = self._conn.execute(
            "SELECT gate_a_trusted FROM accounts WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        return row is not None and row[0] == 1

    def view(self, customer_id: str, as_of: date) -> AccountView:
        row = self._conn.execute(
            "SELECT account_status, balance_cents, contract_start_date FROM accounts "
            "WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        if row is None:
            raise KeyError(customer_id)
        status, balance_cents, start = str(row[0]), int(row[1]), date.fromisoformat(row[2])
        year = contract_year(start, as_of)
        count, withdrawn = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(gross_cents), 0) FROM transactions "
            "WHERE customer_id = ? AND contract_year = ?",
            (customer_id, year),
        ).fetchone()
        return AccountView(
            customer_id=customer_id,
            account_status=AccountStatus(status),
            contract_year=year,
            age_band=self._identity.age_band(customer_id, as_of),
            balance_cents=balance_cents,
            allowance_remaining_cents=free_allowance_cents(balance_cents, int(withdrawn)),
            withdrawals_this_year=int(count),
            contract_start_date=start,  # #176
        )
