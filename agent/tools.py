"""The six servicing tools, grouped by risk tier.

Safety is enforced by CONSTRUCTION, not by trusting the model:
- Account tools read the caller from identity.current_customer_id() — no tool takes
  a customer id, so none can reach another customer's data.
- Account-specific tools refuse until identity.is_verified().
- execute_withdrawal hard-refuses unless verified; confirmation is required by the
  prompt and checked in the evals.
"""
from langchain_core.tools import tool

from agent import identity, withdrawal
from data import accounts, retriever

_VERIFY_MSG = ("[VERIFICATION REQUIRED] I need to verify your identity before I can "
               "share account details or process a withdrawal. Please confirm your "
               "date of birth (YYYY-MM-DD) and the last four digits of your SSN.")


# ============================ Tier 1 — read-only =============================

@tool
def search_knowledge_base(query: str) -> str:
    """Answer product questions (fees, surrender charges, terms, FAQs) using SPR's
    official knowledge base. Use for any general product question. No verification
    needed — this is public product information."""
    hits = retriever.search(query, k=3)
    if not hits:
        return "[source: KB] No matching product information found."
    return "\n\n---\n\n".join(f"[source: KB · {h['source']}]\n{h['text'].strip()}" for h in hits)


@tool
def get_account_details() -> str:
    """Get the CURRENT customer's account details (balance, contract year, status).
    Requires a verified identity."""
    if not identity.is_verified():
        return _VERIFY_MSG
    a = accounts.get_account(identity.current_customer_id())
    return (f"[source: account] {a['name']} · {a['account_status']} account\n"
            f"- Balance: ${a['balance']:,.2f}\n"
            f"- Contract year: {a['contract_year']} of 7\n"
            f"- Guaranteed rate: 4.25% (SecureGrowth Fixed Annuity)")


@tool
def calculate_withdrawal(amount: float) -> str:
    """Show the surrender charge, fees, and NET amount for a proposed withdrawal —
    a safe quote that does NOT move any money. Requires a verified identity. Use
    this to present the cost BEFORE asking the customer to confirm."""
    if not identity.is_verified():
        return _VERIFY_MSG
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return "Please provide a valid withdrawal amount."
    if amount <= 0:
        return "The withdrawal amount must be greater than zero."
    a = accounts.get_account(identity.current_customer_id())
    b = withdrawal.compute(a["balance"], a["contract_year"], amount)
    if amount > a["balance"]:
        return (f"[source: account] That amount (${amount:,.2f}) exceeds your balance "
                f"of ${a['balance']:,.2f}.")
    return "[quote — no money moved]\n" + withdrawal.format_breakdown(b)


# ==================== Tier 3 — high-risk (verify + confirm) ==================

@tool
def execute_withdrawal(amount: float) -> str:
    """Actually process a withdrawal. Call this ONLY after (1) identity is verified
    AND (2) you have shown the customer the exact charges and they explicitly
    confirmed. It is irreversible. If either precondition is missing, do not call it."""
    if not identity.is_verified():
        return ("[BLOCKED] I can't process a withdrawal until your identity is verified. "
                + _VERIFY_MSG)
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return "Please provide a valid withdrawal amount."
    if amount <= 0:
        return "The withdrawal amount must be greater than zero."
    a = accounts.get_account(identity.current_customer_id())
    if amount > a["balance"]:
        return f"[BLOCKED] ${amount:,.2f} exceeds your balance of ${a['balance']:,.2f}."
    b = withdrawal.compute(a["balance"], a["contract_year"], amount)
    return ("[PROCESSED] Your withdrawal has been submitted and will settle in 5–7 "
            "business days.\n" + withdrawal.format_breakdown(b))


# ============================== Handoff =====================================

@tool
def verify_identity(date_of_birth: str = None, last4_ssn: str = None) -> str:
    """Verify the current customer's identity using their date of birth (YYYY-MM-DD)
    and the last four digits of their SSN. Both must match the record."""
    if accounts.check_identity(identity.current_customer_id(), date_of_birth, last4_ssn):
        identity.mark_verified()
        return "[VERIFIED] Identity confirmed. How can I help with your account?"
    return ("[NOT VERIFIED] Those details don't match our records. I can't share "
            "account information or process transactions until identity is verified.")


@tool
def escalate_to_human(reason: str) -> str:
    """Hand off to a licensed SPR representative when you should not act on your own
    (hardship or documentation-dependent waivers, disputes, unclear high-risk requests,
    or anything outside these tools)."""
    return ("[ESCALATED] I'm connecting you with a licensed SPR Financials "
            "representative who can help with this. Reason noted: " + str(reason))


READONLY_TOOLS = [search_knowledge_base, get_account_details, calculate_withdrawal]
SENSITIVE_TOOLS = [execute_withdrawal]
GATE_TOOLS = [verify_identity]
HANDOFF_TOOLS = [escalate_to_human]
ALL_TOOLS = READONLY_TOOLS + GATE_TOOLS + SENSITIVE_TOOLS + HANDOFF_TOOLS
