"""Customer data access — reads the provided accounts.json directly.

The authoritative source for balances, contract years, and identity facts. Only
4 records, so a thin JSON layer is the most faithful, lowest-friction choice
(no DB server, runs from a clean checkout).

Reads are by customer_id only; nothing here takes a "give me everyone" shape, so
a tool built on it can only ever surface one customer.
"""
import json

import config

_ACCOUNTS = None


def _load():
    global _ACCOUNTS
    if _ACCOUNTS is None:
        with open(config.ACCOUNTS_PATH, "r", encoding="utf-8") as f:
            _ACCOUNTS = {a["customer_id"]: a for a in json.load(f)["accounts"]}
    return _ACCOUNTS


def get_account(customer_id: str):
    return _load().get(customer_id)


def all_customer_ids():
    return list(_load())


def check_identity(customer_id: str, dob: str = None, last4_ssn: str = None) -> bool:
    """True only if the supplied identifiers match this customer's record.
    Requires BOTH a matching DOB and last-4 SSN (two factors)."""
    acct = get_account(customer_id)
    if not acct:
        return False
    dob_ok = dob is not None and str(dob).strip() == acct["dob"]
    ssn_ok = last4_ssn is not None and str(last4_ssn).strip() == acct["last4_ssn"]
    return dob_ok and ssn_ok
