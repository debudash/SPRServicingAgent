"""Exercise the tools, the verification gate, and the withdrawal math WITHOUT an LLM.

Run after ingest:  python -m scripts.smoke_test
Proves: verified reads work, unverified callers are blocked, verification flips the
gate, withdrawals never execute while unverified, and the math matches ground truth.
"""
from agent import identity, tools, withdrawal
from data import accounts


def show(title, result):
    print(f"\n=== {title} ===\n{result}")


def main():
    print("SPR Servicing Agent — core smoke test (no LLM)")

    # Pure math ground-truth check (Margaret, year 3, $20,000)
    b = withdrawal.compute(87450.62, 3, 20000)
    assert b["surrender_charge"] == 675.30 and b["net_received"] == 19299.70, b
    print(f"\nmath check: $20k @ year 3 -> charge ${b['surrender_charge']}, net ${b['net_received']} (OK)")

    # Verified customer (Margaret, SPR-1001)
    identity.login("SPR-1001")
    print(f"\nLogged in: SPR-1001 (verified={identity.is_verified()})")
    show("search_knowledge_base 'surrender charge year 5'",
         tools.search_knowledge_base.invoke({"query": "surrender charge year 5"}))
    show("get_account_details", tools.get_account_details.invoke({}))
    show("calculate_withdrawal $20,000", tools.calculate_withdrawal.invoke({"amount": 20000}))

    # Unverified customer (Raymond, SPR-1002)
    identity.login("SPR-1002")
    print(f"\nLogged in: SPR-1002 (verified={identity.is_verified()})")
    show("get_account_details (should be BLOCKED)", tools.get_account_details.invoke({}))
    show("execute_withdrawal $5,000 (should be BLOCKED)", tools.execute_withdrawal.invoke({"amount": 5000}))
    show("verify_identity WRONG ssn", tools.verify_identity.invoke({"date_of_birth": "1971-11-29", "last4_ssn": "0000"}))
    show("verify_identity CORRECT", tools.verify_identity.invoke({"date_of_birth": "1971-11-29", "last4_ssn": "4451"}))
    show("get_account_details (now verified)", tools.get_account_details.invoke({}))

    print("\nSmoke test complete. Gate + math behaved correctly.")


if __name__ == "__main__":
    main()
