"""Tri-tier guardrail model — agent design as risk management.

Two orthogonal controls:
  * IDENTITY (agent/identity.py) — two gates in series, neither settable by the
    model: the account must be verified on SPR's records (Gate A, out of band) AND
    the caller must pass this session's DOB + last-4-SSN challenge (Gate B).
  * RISK TIER (here) — how much autonomy an action gets.

  Tier 1  read-only advisory          -> autonomous (but account reads need both gates)
  Tier 2  verification                -> the session challenge itself (Gate B)
  Tier 3  high-risk / irreversible    -> execute_withdrawal: both gates + the amount
                                         already quoted, else refuse/escalate
"""
TIER_1 = "read_only"
TIER_2 = "verification"
TIER_3 = "high_risk"
HANDOFF = "handoff"

TOOL_TIERS = {
    "search_knowledge_base": TIER_1,
    "get_account_details": TIER_1,
    "calculate_withdrawal": TIER_1,
    "verify_identity": TIER_2,
    "execute_withdrawal": TIER_3,
    "escalate_to_human": HANDOFF,
}

TIER_LABEL = {TIER_1: "read-only", TIER_2: "identity check",
              TIER_3: "high-risk (verify + confirm)", HANDOFF: "handoff"}


def tier_of(tool_name: str) -> str:
    return TOOL_TIERS.get(tool_name, TIER_1)


def needs_human_approval(tool_name: str) -> bool:
    return tier_of(tool_name) == TIER_3
