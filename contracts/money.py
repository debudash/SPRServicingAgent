"""Money rules shared by every lane (GR-03).

Amounts are integer cents; rounding is half-up, in code.
"""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def to_cents(amount: Decimal) -> int:
    """Round a dollar amount half-up to the cent and return it as integer cents."""
    return int((amount.quantize(CENT, rounding=ROUND_HALF_UP) * 100).to_integral_value())


def to_dollars(cents: int) -> Decimal:
    return (Decimal(cents) / 100).quantize(CENT)


def format_dollars(cents: int) -> str:
    """Customer-facing format, e.g. 1932470 -> '$19,324.70'."""
    return f"${to_dollars(cents):,.2f}"


def surrender_charge_cents(excess_cents: int, rate_bp: int) -> int:
    """Surrender charge on the excess, half-up to the cent (fee_schedule.md, GR-03).

    The one place the charge rule lives: the quote calculator and the Quote contract both use it.
    """
    exact = Decimal(excess_cents) * Decimal(rate_bp) / Decimal(10_000)
    return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))
