"""Integrity checks on the answer key itself (integrator-owned, protected from agent PRs).

These tests do not run the agent. They make sure the golden set is well-formed, that every grounding
rule is pinned by at least one case, that every PRD reference exists, and that every expected quote
recomputes exactly from the starter data. A wrong number in the answer key would otherwise grade the
agent against a mistake.
"""

import json
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).resolve().parent
KIT = ROOT / "problemstmt" / "spr_starter_kit"
AS_OF = date(2024, 12, 1)  # PRD D-04
LARGE_AMOUNT = Decimal("25000")  # PRD D-02
LARGE_SHARE = Decimal("0.5")  # PRD D-02

BULLETS = {"B1", "B2", "B3", "B4", "B5"}
OUTCOMES = {
    "ANSWERED",
    "EXECUTED",
    "NO_SOURCE",
    "NOT_PERMITTED",
    "NEEDS_HUMAN",
    "UNAVAILABLE",
    "OUT_OF_SCOPE",
}
STATUSES = {"active", "pending_data", "retired"}
SESSION_KEYS = {"step_up"}  # ADR 0007: `gate_b_passed` is gone; a customer case logs in
STEP_UP_MODES = {"auto", "manual"}
TURN_KINDS = {"user", "step_up", "reviewer"}
TIERS = {"self_service", "human"}
CENT = Decimal("0.01")


def _cases(name: str) -> list[dict[str, Any]]:
    data = yaml.safe_load((GOLDEN / name).read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = data["cases"]
    return cases


ALL = [("golden", c) for c in _cases("golden.yaml")] + [
    ("behavioural", c) for c in _cases("behavioural.yaml")
]


def _ids_in(path: Path, pattern: str) -> set[str]:
    return set(re.findall(pattern, path.read_text(encoding="utf-8")))


RULES = _ids_in(ROOT / "docs" / "GROUNDING_RULES.md", r"\*\*(GR-\d{2})\b")
PRD_IDS = _ids_in(ROOT / "docs" / "PRD.md", r"\b((?:FR|NG|PG|M|D)-\d{2})\b")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _accounts() -> dict[str, dict[str, Any]]:
    raw = json.loads((KIT / "data" / "accounts.json").read_text(encoding="utf-8"))
    return {a["customer_id"]: a for a in raw["accounts"]}


def _rates() -> dict[int, Decimal]:
    text = (KIT / "knowledge_base" / "fee_schedule.md").read_text(encoding="utf-8")
    return {
        int(y): Decimal(r) / 100 for y, r in re.findall(r"\|\s*Year (\d)\s*\|\s*(\d+)%\s*\|", text)
    }


def _age_under_59_and_a_half(dob: str) -> bool:
    born = date.fromisoformat(dob)
    months = (AS_OF.year - born.year) * 12 + (AS_OF.month - born.month) - (AS_OF.day < born.day)
    return months < 59 * 12 + 6


def test_ids_are_unique() -> None:
    ids = [c["id"] for _, c in ALL]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(("kind", "case"), ALL, ids=[c["id"] for _, c in ALL])
def test_case_is_well_formed(kind: str, case: dict[str, Any]) -> None:
    assert case["bullet"] in BULLETS
    assert case["id"].split("-")[1] == case["bullet"], "the ID names its bullet"
    assert case["rules"] and set(case["rules"]) <= RULES, "every rule cited exists"
    assert case["prd"] and set(case["prd"]) <= PRD_IDS, "every PRD item cited exists"
    assert case.get("status", "active") in STATUSES
    expect = case["expect"]
    if kind == "golden":
        assert case["ask"]
        assert expect.get("outcome", "ANSWERED") in OUTCOMES
    else:
        assert case["turns"]
        assert expect.get("final_outcome", "ANSWERED") in OUTCOMES
        for turn in case["turns"]:
            assert len(turn) == 1 and set(turn) <= TURN_KINDS, f"one kind per turn: {turn}"
            if "step_up" in turn:
                answer = turn["step_up"]
                if answer != "correct":
                    assert sorted(answer) == ["dob", "last4"], answer
                    assert str(answer["last4"]).isdigit(), answer
    session = case.get("session") or {}
    assert set(session) <= SESSION_KEYS, f"unknown session keys: {set(session) - SESSION_KEYS}"
    assert session.get("step_up", "auto") in STEP_UP_MODES
    scripted = any("step_up" in t for t in case.get("turns", []))
    assert not scripted or session.get("step_up") == "manual", "a scripted step-up is manual"
    if scripted:
        assert case["customer"], "only a logged-in customer can step up"


def pinned_rules(cases: list[dict[str, Any]]) -> set[str]:
    """The rules pinned by cases that run. Issue #118 (found by /code-review on PR #117): retired
    and pending cases counted too, so a rule held only by a case that never runs passed."""
    return {rule for c in cases if c.get("status", "active") == "active" for rule in c["rules"]}


# Rules whose only case waits on data (`pending_data`): named here, with the reason, so the gap is
# visible and reviewed rather than hidden by counting a case that never runs (#118).
# Empty since #123: BH-B4-02 runs on the synthetic superseded fee schedule.
AWAITING_DATA: dict[str, str] = {}


def test_every_rule_is_pinned_by_a_case() -> None:
    cases = [c for _, c in ALL]
    unpinned = RULES - pinned_rules(cases)
    assert unpinned == set(AWAITING_DATA), f"rules with no running case: {sorted(unpinned)}"
    for rule in AWAITING_DATA:  # each exception really rests on a pending case
        assert any(rule in c["rules"] and c.get("status") == "pending_data" for c in cases), rule


QUOTED = [c for _, c in ALL if "quote" in c]


@pytest.mark.parametrize("case", QUOTED, ids=[c["id"] for c in QUOTED])
def test_expected_quote_recomputes_from_starter_data(case: dict[str, Any]) -> None:
    # D-05: free allowance = 10% of the current balance minus withdrawals this contract year.
    # The starter accounts have no withdrawals on file, so the allowance is 10% of the balance.
    q = case["quote"]
    account = _accounts()[case["customer"]]
    balance = Decimal(str(account["balance"]))
    amount = Decimal(q["amount"])
    rate = _rates()[account["contract_year"]]

    free = _money(balance * Decimal("0.10"))
    excess = max(Decimal("0.00"), amount - free)
    charge = _money(excess * rate)
    large = amount > LARGE_AMOUNT or amount > balance * LARGE_SHARE

    assert Decimal(q["free"]) == free
    assert Decimal(q["excess"]) == excess
    assert Decimal(q["rate"].rstrip("%")) / 100 == rate
    assert Decimal(q["charge"]) == charge
    assert Decimal(q["net"]) == amount - charge
    assert q["threshold_tier"] in TIERS
    assert q["threshold_tier"] == ("human" if large else "self_service")
    assert q["irs_notice"] == _age_under_59_and_a_half(account["dob"])


def test_a_retired_case_says_why() -> None:
    for _, case in ALL:
        if case.get("status") == "retired":
            assert "Retired" in case.get("note", ""), case["id"]


# ---------- #118: the rule-pinning check counted retired and pending cases ----------
# Found by /code-review on PR #117 (spec): a rule held only by a case that never runs passed.
def test_issue_118_only_active_cases_pin_a_rule() -> None:
    cases: list[dict[str, Any]] = [
        {"rules": ["GR-01"], "status": "retired"},
        {"rules": ["GR-02"], "status": "pending_data"},
        {"rules": ["GR-03"]},
    ]
    assert pinned_rules(cases) == {"GR-03"}
