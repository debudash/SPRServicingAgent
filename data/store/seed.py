"""Load the starter kit's accounts into desk.db, once (issue #57).

`identity_verified` becomes `gate_a_trusted`; date of birth and SSN digits go to the identity table
through data/identity.py and nowhere else.
"""

import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

from contracts.money import to_cents
from data.identity import SqliteIdentityCheck

STARTER_KIT = (
    Path(__file__).resolve().parents[2]
    / "problemstmt"
    / "spr_starter_kit"
    / "data"
    / "accounts.json"
)


def _cents(value: Any) -> int:
    return to_cents(Decimal(str(value)))  # via str: the JSON float is the printed amount


def seed_starter_kit(conn: sqlite3.Connection, path: Path = STARTER_KIT) -> int:
    """Insert every account not already present; return how many were inserted."""
    identity = SqliteIdentityCheck(conn)
    inserted = 0
    for a in json.loads(path.read_text(encoding="utf-8"))["accounts"]:
        exists = conn.execute(
            "SELECT 1 FROM accounts WHERE customer_id = ?", (a["customer_id"],)
        ).fetchone()
        if exists:
            continue
        conn.execute("BEGIN")  # one account at a time: all its rows, or none
        try:
            _insert_account(conn, identity, a)
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        inserted += 1
    return inserted


def _insert_account(conn: sqlite3.Connection, identity: SqliteIdentityCheck, a: Any) -> None:
    cid = a["customer_id"]
    conn.execute(
        "INSERT INTO accounts (customer_id, name, email, phone, account_status, "
        "gate_a_trusted, balance_cents, initial_deposit_cents, contract_start_date, "
        "contract_year_stored, is_synthetic) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
        (
            cid,
            a["name"],
            a.get("email"),
            a.get("phone"),
            a["account_status"],
            1 if a["identity_verified"] else 0,
            _cents(a["balance"]),
            _cents(a["initial_deposit"]),
            a["contract_start_date"],
            a.get("contract_year"),
        ),
    )
    identity.store(cid, str(a["dob"]), str(a["last4_ssn"]))
    for b in a.get("beneficiaries", []):
        conn.execute(
            "INSERT INTO beneficiaries (customer_id, name, relationship, percentage) "
            "VALUES (?, ?, ?, ?)",
            (cid, b["name"], b["relationship"], b["percentage"]),
        )
