"""Tri-tier guardrail model — agent design as risk management.

Two orthogonal controls:
  * IDENTITY (agent/identity.py) — account-specific tools refuse until the caller
    is verified; the model can't set this itself.
  * RISK TIER (here) — how much autonomy an action gets.

  Tier 1  read-only advisory          -> autonomous (but account reads need verify)
  Tier 2  verification                -> the identity gate itself
  Tier 3  high-risk / irreversible    -> execute_withdrawal: verified + explicit
                                         confirmation, else refuse/escalate
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
