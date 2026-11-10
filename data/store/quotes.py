"""The quote calculator (FR-05 to FR-07, D-02, D-05): every figure from records and code.

Built on the account view, so the contract year, the remaining free allowance and the age band are
computed in exactly one place for the account answer and the quote alike.
"""

from datetime import date

from contracts.messages import (
    AccountStatus,
    AgeBand,
    Quote,
    QuoteRefusal,
    QuoteRefusalReason,
    ThresholdTier,
)
from contracts.money import surrender_charge_cents
from data.store.accounts import SqliteAccountStore

# fee_schedule.md, in basis points. Year 7 and later: no charge. Year 5 is 3%, not 4%.
SURRENDER_RATE_BP = {1: 800, 2: 700, 3: 600, 4: 500, 5: 300, 6: 100}
HUMAN_OVER_CENTS = 2_500_000  # D-02: over $25,000 goes to a human


def surrender_rate_bp(contract_year: int) -> int:
    return SURRENDER_RATE_BP.get(contract_year, 0)


def threshold_tier(amount_cents: int, balance_cents: int) -> ThresholdTier:
    """D-02: over $25,000, or over 50% of the balance, is the human tier. Exactly on a line is not
    over it."""
    if amount_cents > HUMAN_OVER_CENTS or amount_cents * 2 > balance_cents:
        return ThresholdTier.HUMAN
    return ThresholdTier.SELF_SERVICE


class SqliteQuoteService:
    def __init__(self, accounts: SqliteAccountStore) -> None:
        self._accounts = accounts

    def quote(self, customer_id: str, amount_cents: int, as_of: date) -> Quote | QuoteRefusal:
        view = self._accounts.view(customer_id, as_of)  # KeyError for an unknown customer
        if view.account_status is not AccountStatus.ACTIVE:
            return QuoteRefusal(reason=QuoteRefusalReason.NOT_ACTIVE)
        if amount_cents <= 0:
            return QuoteRefusal(reason=QuoteRefusalReason.NOT_POSITIVE)
        if amount_cents > view.balance_cents:
            return QuoteRefusal(reason=QuoteRefusalReason.OVER_BALANCE)
        free = view.allowance_remaining_cents
        excess = max(0, amount_cents - free)
        rate = surrender_rate_bp(view.contract_year)
        charge = surrender_charge_cents(excess, rate)
        return Quote(
            amount_cents=amount_cents,
            free_cents=free,
            excess_cents=excess,
            rate_bp=rate,
            charge_cents=charge,
            net_cents=amount_cents - charge,
            contract_year=view.contract_year,
            threshold_tier=threshold_tier(amount_cents, view.balance_cents),
            irs_notice=view.age_band is AgeBand.UNDER_59_5,  # FR-06
        )
