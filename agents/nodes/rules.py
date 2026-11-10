"""rules (code): the checks Compliance can never override (FR-11, ARCHITECTURE 3.3, #89).

Computed from records, not from the model: the D-02 threshold (over $25,000, or over half the
current balance), the account's status now (a change since the quote, issue #24), the D-07 age rule
(80 or over, beyond the free allowance) and the FR-26 kill switch. Any flag sends the proposal to a
person; Compliance only sees a proposal with none.
"""

from typing import Any

from pydantic import JsonValue

from agents.nodes.common import Deps, NodeFn
from contracts.messages import (
    AccountStatus,
    AgeBand,
    CaseReason,
    Quote,
    RuleFlag,
    RuleFlags,
    ThresholdTier,
)
from contracts.ports import AuditEvent
from contracts.state import ConversationState
from contracts.tools import Node

LARGE_AMOUNT_CENTS = 2_500_000  # D-02: over $25,000


def flags_for(
    quote: Quote, execution_enabled: bool, view_status: AccountStatus, balance: int, age: AgeBand
) -> set[RuleFlag]:
    """The flags for a quote against the account as it is now."""
    flags: set[RuleFlag] = set()
    if quote.amount_cents > LARGE_AMOUNT_CENTS:
        flags.add(RuleFlag.OVER_AMOUNT)
    # D-02 on the current balance, and the tier the quote was given: either makes it human.
    if quote.amount_cents * 2 > balance:
        flags.add(RuleFlag.OVER_SHARE)
    if quote.threshold_tier is ThresholdTier.HUMAN and not flags:
        # Human tier at quote time but under $25,000: it was the share of the balance then.
        flags.add(RuleFlag.OVER_SHARE)
    if view_status is not AccountStatus.ACTIVE:
        flags.add(RuleFlag.NOT_ACTIVE)
    if age is AgeBand.EIGHTY_PLUS and quote.excess_cents > 0:
        flags.add(RuleFlag.AGE_80_OVER_ALLOWANCE)
    if not execution_enabled:
        flags.add(RuleFlag.EXECUTION_DISABLED)
    return flags


def _review_open(deps: Deps, conversation_id: str) -> bool:
    """Whether this conversation already opened a withdrawal-review case (#136)."""
    return any(
        row.event is AuditEvent.CASE_OPENED
        and row.payload.get("opened_for") == CaseReason.WITHDRAWAL_REVIEW.value
        for row in deps.audit.read(conversation_id)
    )


def make(deps: Deps) -> NodeFn:
    def rules(state: ConversationState) -> dict[str, Any]:
        proposal, customer_id = state.proposal, state.session.customer_id
        if proposal is None or customer_id is None:
            return {}
        view = deps.accounts.view(customer_id, state.as_of)
        flags = flags_for(
            proposal.quote,
            state.switches.execution_enabled,
            view.account_status,
            view.balance_cents,
            view.age_band,
        )
        # Issue #136: a hold or escalation sent one proposal to a person, and the next proposal
        # in the same session started clean, so asking again (or for a smaller part) executed.
        # The audit log is the durable record of the cases this conversation opened: once a
        # withdrawal is with a person, every later one in the session goes to a person too.
        if _review_open(deps, state.conversation_id):
            flags.add(RuleFlag.OPEN_REVIEW)
        if flags:
            names: list[JsonValue] = [f.value for f in sorted(flags)]
            deps.audit.append(
                conversation_id=state.conversation_id,
                turn=state.turn,
                node=Node.RULES,
                event=AuditEvent.RULE_FLAGGED,
                payload={
                    "proposal_id": proposal.proposal_id,
                    "flags": names,
                },
                versions=state.versions.model_dump(mode="json"),
            )
        return {"rule_flags": RuleFlags(proposal_id=proposal.proposal_id, flags=frozenset(flags))}

    return rules
