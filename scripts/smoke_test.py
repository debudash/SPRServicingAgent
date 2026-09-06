"""Exercise the tools, BOTH identity gates, and the withdrawal math WITHOUT an LLM.

Run after ingest:  python -m scripts.smoke_test

Fast, deterministic, no API key. Proves, in order:
  1. the surrender math matches ground truth
  2. Gate B blocks a trusted account until the caller passes the DOB + last-4 challenge
  3. execute_withdrawal refuses an amount that was never quoted
  4. a quoted withdrawal then processes
  5. Gate A blocks an account SPR never verified — even with correct credentials

Every step asserts; the script exits non-zero if any gate fails to hold.
"""
import sys

from agent import identity, tools, withdrawal

_checks = {"passed": 0, "failed": 0}


def check(label, condition):
    ok = bool(condition)
    _checks["passed" if ok else "failed"] += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    return ok


def show(title, result):
    body = " ".join(str(result).split())
    print(f"\n  > {title}\n    {body[:220]}{'...' if len(body) > 220 else ''}")
    return result


def main():
    print("SPR Servicing Agent — core smoke test (no LLM, no API key)")

    # ---------------------------------------------------------------- math
    print("\n--- Deterministic math (the eval harness imports this same function) ---")
    b = withdrawal.compute(87450.62, 3, 20000)
    check(f"$20k in year 3 -> charge ${b['surrender_charge']}, net ${b['net_received']}",
          b["surrender_charge"] == 675.30 and b["net_received"] == 19299.70)

    # -------------------------------------------- Gate B (trusted account)
    print("\n--- Margaret (SPR-1001): account trusted, caller not yet challenged ---")
    identity.login("SPR-1001")
    check("Gate A passes (verified on SPR's record)", identity.account_is_trusted())
    check("Gate B starts unpassed, even for a trusted account",
          not identity.challenge_passed())

    r = show("get_account_details", tools.get_account_details.invoke({}))
    check("balance withheld until the caller is challenged", "87,450" not in r)

    r = show("verify_identity with the WRONG last-4",
             tools.verify_identity.invoke({"date_of_birth": "1958-03-14", "last4_ssn": "0000"}))
    check("wrong credentials refused", "[NOT VERIFIED]" in r)

    r = show("verify_identity with the CORRECT details",
             tools.verify_identity.invoke({"date_of_birth": "1958-03-14", "last4_ssn": "7823"}))
    check("correct credentials pass Gate B", "[VERIFIED]" in r and identity.challenge_passed())

    r = show("get_account_details (both gates now pass)", tools.get_account_details.invoke({}))
    check("balance released once both gates pass", "87,450.62" in r)

    # ------------------------------------------------ quote before execute
    print("\n--- Quote-before-execute is enforced in code, not just prompted ---")
    r = show("execute_withdrawal $20,000 — never quoted",
             tools.execute_withdrawal.invoke({"amount": 20000}))
    check("refuses an amount the customer was never shown", "[BLOCKED]" in r)

    r = show("calculate_withdrawal $20,000", tools.calculate_withdrawal.invoke({"amount": 20000}))
    check("quote shows the real surrender charge", "675.30" in r)

    r = show("execute_withdrawal $20,000 — now quoted",
             tools.execute_withdrawal.invoke({"amount": 20000}))
    check("processes once the charges have been shown", "[PROCESSED]" in r)

    # ------------------------------------------ Gate A (untrusted account)
    print("\n--- Raymond (SPR-1002): account SPR never verified ---")
    identity.login("SPR-1002")
    check("Gate A fails (not verified on SPR's record)", not identity.account_is_trusted())

    r = show("get_account_details", tools.get_account_details.invoke({}))
    check("blocked, and told to verify with SPR directly",
          "42,100" not in r and "[ACCOUNT NOT VERIFIED]" in r)

    r = show("verify_identity with his CORRECT details",
             tools.verify_identity.invoke({"date_of_birth": "1971-11-29", "last4_ssn": "4451"}))
    check("correct credentials grant nothing on an untrusted account",
          "[VERIFIED]" not in r and not identity.challenge_passed())

    r = show("execute_withdrawal $5,000", tools.execute_withdrawal.invoke({"amount": 5000}))
    check("withdrawal still refused", "[BLOCKED]" in r)

    r = show("search_knowledge_base 'surrender charge year 5'",
             tools.search_knowledge_base.invoke({"query": "surrender charge year 5"}))
    check("public product info still available to an unverified caller", "3%" in r)

    identity.logout()
    total = _checks["passed"] + _checks["failed"]
    print(f"\n{_checks['passed']} of {total} checks passed.")
    if _checks["failed"]:
        print("A gate did not hold — see the FAIL lines above.")
    return 1 if _checks["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
