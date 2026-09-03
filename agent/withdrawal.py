"""Pure withdrawal math — the deterministic ground truth from the SPR fee schedule.

Kept as a standalone, side-effect-free function so both the tools AND the eval
harness import the exact same calculation (no drift between what the agent does
and what we grade it against).

Rules (knowledge_base/fee_schedule.md):
- Free withdrawal allowance = 10% of account balance per contract year (no charge).
- Surrender charge = (withdrawal - free allowance) x rate[contract_year], on the
  EXCESS above the free amount only.
- Wire transfer fee = $25 flat for withdrawals over $10,000.
"""

SURRENDER_SCHEDULE = {1: 0.08, 2: 0.07, 3: 0.06, 4: 0.05, 5: 0.03, 6: 0.01, 7: 0.00}
FREE_WITHDRAWAL_PCT = 0.10
WIRE_FEE = 25.00
WIRE_THRESHOLD = 10000.00


def compute(balance: float, contract_year: int, amount: float) -> dict:
    free = round(balance * FREE_WITHDRAWAL_PCT, 2)
    excess = round(max(0.0, amount - free), 2)
    rate = SURRENDER_SCHEDULE.get(contract_year, 0.0)
    surrender_charge = round(excess * rate, 2)
    wire_fee = WIRE_FEE if amount > WIRE_THRESHOLD else 0.0
    net = round(amount - surrender_charge - wire_fee, 2)
    return {
        "amount": round(amount, 2),
        "contract_year": contract_year,
        "free_withdrawal": free,
        "excess_over_free": excess,
        "surrender_rate": rate,
        "surrender_charge": surrender_charge,
        "wire_fee": wire_fee,
        "net_received": net,
    }


def format_breakdown(b: dict) -> str:
    return (
        f"Withdrawal: ${b['amount']:,.2f} (contract year {b['contract_year']})\n"
        f"- Free allowance (10%): ${b['free_withdrawal']:,.2f}\n"
        f"- Amount above free: ${b['excess_over_free']:,.2f}\n"
        f"- Surrender rate: {b['surrender_rate']*100:.0f}%\n"
        f"- Surrender charge: ${b['surrender_charge']:,.2f}\n"
        f"- Wire fee: ${b['wire_fee']:,.2f}\n"
        f"- Net you would receive: ${b['net_received']:,.2f}"
    )
