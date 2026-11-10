"""Contract tests for the B3 additions (issue #86): quote, proposal, token and ledger ports."""

import inspect
from datetime import date
from itertools import pairwise

import pytest
from pydantic import JsonValue, ValidationError

from contracts.messages import (
    DECISION_MOVES,
    PROPOSAL_TRANSITIONS,
    Approval,
    Confirmation,
    Decision,
    Execution,
    Proposal,
    ProposalStatus,
    Quote,
    QuoteRefusal,
    QuoteRefusalReason,
    ThresholdTier,
    check_confirmation,
    check_transition,
    proposal_hash,
)
from contracts.ports import (
    ApprovalStore,
    ExecutionRefused,
    ExecutionRefusedReason,
    KnowledgeChunk,
    Ledger,
    PolicySource,
    ProposalStore,
    QuoteService,
)
from contracts.tokens import approval_token, tokens_match

AS_OF = date(2024, 12, 1)
# G-B3-01: SPR-1001 withdraws $20,000 in contract year 3.
QUOTE = Quote(
    amount_cents=2_000_000,
    free_cents=874_506,
    excess_cents=1_125_494,
    rate_bp=600,
    charge_cents=67_530,
    net_cents=1_932_470,
    contract_year=3,
    threshold_tier=ThresholdTier.SELF_SERVICE,
    irs_notice=False,
)


def _proposal() -> Proposal:
    return Proposal(
        proposal_id="P-1",
        conversation_id="CV1",
        customer_id="SPR-1001",
        quote=QUOTE,
        as_of=AS_OF,
        quoted_turn=1,
        hash=proposal_hash("SPR-1001", QUOTE, AS_OF),
    )


# ---------- FR-07: a refused quote says why ----------
def test_quote_refusal_reasons_cover_fr_07() -> None:
    assert {r.value for r in QuoteRefusalReason} == {"not_positive", "over_balance", "not_active"}
    assert (
        QuoteRefusal(reason=QuoteRefusalReason.OVER_BALANCE).reason
        is QuoteRefusalReason.OVER_BALANCE
    )
    with pytest.raises(ValidationError):
        QuoteRefusal.model_validate({"reason": "because"})


# ---------- the proposal status machine (ARCHITECTURE 2.2) ----------
def test_every_status_has_its_transitions() -> None:
    assert set(PROPOSAL_TRANSITIONS) == set(ProposalStatus)


def test_the_happy_path_is_quoted_confirmed_approved_executed() -> None:
    path = [
        ProposalStatus.QUOTED,
        ProposalStatus.CONFIRMED,
        ProposalStatus.APPROVED,
        ProposalStatus.EXECUTED,
    ]
    for before, after in pairwise(path):
        assert after in PROPOSAL_TRANSITIONS[before]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (ProposalStatus.QUOTED, ProposalStatus.APPROVED),  # no approval without a yes (GR-17)
        (ProposalStatus.QUOTED, ProposalStatus.EXECUTED),
        (ProposalStatus.CONFIRMED, ProposalStatus.EXECUTED),  # no execution without approval
        (ProposalStatus.EXECUTED, ProposalStatus.VOIDED),  # executed is final
        (ProposalStatus.VOIDED, ProposalStatus.CONFIRMED),  # voided is final
    ],
)
def test_illegal_transitions_are_absent(before: ProposalStatus, after: ProposalStatus) -> None:
    assert after not in PROPOSAL_TRANSITIONS[before]


def test_terminal_statuses_go_nowhere() -> None:
    assert PROPOSAL_TRANSITIONS[ProposalStatus.EXECUTED] == frozenset()
    assert PROPOSAL_TRANSITIONS[ProposalStatus.VOIDED] == frozenset()


# ---------- approval tokens (GR-18): bound to the proposal hash ----------
def test_token_is_bound_to_hash_and_secret() -> None:
    h = _proposal().hash
    token = approval_token("P-1", h, b"secret-a")
    assert token == approval_token("P-1", h, b"secret-a")
    assert token != approval_token("P-1", h, b"secret-b")
    other = proposal_hash("SPR-1001", QUOTE.model_copy(update={"irs_notice": True}), AS_OF)
    assert token != approval_token("P-1", other, b"secret-a")
    assert tokens_match(token, approval_token("P-1", h, b"secret-a"))
    assert not tokens_match(token, approval_token("P-1", other, b"secret-a"))


def test_an_empty_secret_is_refused() -> None:
    with pytest.raises(ValueError):
        approval_token("P-1", _proposal().hash, b"")
    with pytest.raises(ValueError):
        approval_token("", _proposal().hash, b"secret")


# ---------- ports ----------
def test_ledger_execute_takes_a_token_and_returns_an_execution() -> None:
    sig = inspect.signature(Ledger.execute)
    assert list(sig.parameters) == ["self", "proposal_id", "token", "turn", "versions"]
    assert sig.return_annotation is Execution
    err = ExecutionRefused(ExecutionRefusedReason.TOKEN_INVALID)
    assert err.reason is ExecutionRefusedReason.TOKEN_INVALID


class _FakeQuotes:
    def quote(self, customer_id: str, amount_cents: int, as_of: date) -> Quote | QuoteRefusal:
        if amount_cents <= 0:
            return QuoteRefusal(reason=QuoteRefusalReason.NOT_POSITIVE)
        return QUOTE


class _FakeProposals:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[Proposal, ProposalStatus]] = {}

    def save(self, proposal: Proposal) -> None:
        self.rows[proposal.proposal_id] = (proposal, ProposalStatus.QUOTED)

    def get(self, proposal_id: str) -> Proposal | None:
        row = self.rows.get(proposal_id)
        return row[0] if row else None

    def status(self, proposal_id: str) -> ProposalStatus:
        return self.rows[proposal_id][1]

    def confirm(self, confirmation: Confirmation, conversation_id: str) -> None:
        check_confirmation(self.rows[confirmation.proposal_id][0], confirmation, conversation_id)
        self.move(confirmation.proposal_id, ProposalStatus.CONFIRMED)

    def move(self, proposal_id: str, status: ProposalStatus) -> None:
        proposal, before = self.rows[proposal_id]
        check_transition(before, status)
        self.rows[proposal_id] = (proposal, status)


class _FakeApprovals:
    def __init__(self) -> None:
        self.recorded: list[Approval] = []

    def record(self, approval: Approval) -> None:
        self.recorded.append(approval)


class _FakeLedger:
    def execute(
        self, proposal_id: str, token: str, turn: int, versions: dict[str, JsonValue]
    ) -> Execution:
        return Execution(transaction_id="TX-1", proposal_id=proposal_id, approved_by="compliance")


class _FakePolicy:
    def get_policy(self, query: str, as_of: date, k: int = 4) -> list[KnowledgeChunk]:
        return []


def test_fakes_conform_to_the_b3_ports() -> None:
    quotes: QuoteService = _FakeQuotes()
    store = _FakeProposals()
    proposals: ProposalStore = store
    approvals: ApprovalStore = _FakeApprovals()
    ledger: Ledger = _FakeLedger()
    policy: PolicySource = _FakePolicy()
    assert isinstance(quotes.quote("SPR-1001", 0, AS_OF), QuoteRefusal)
    proposals.save(_proposal())
    with pytest.raises(ValueError):  # the yes on the quote's own turn (GR-17)
        proposals.confirm(Confirmation(proposal_id="P-1", amount_cents=2_000_000, turn=1), "CV1")
    proposals.confirm(Confirmation(proposal_id="P-1", amount_cents=2_000_000, turn=2), "CV1")
    assert proposals.status("P-1") is ProposalStatus.CONFIRMED
    with pytest.raises(ValueError):
        proposals.move("P-1", ProposalStatus.EXECUTED)  # skipping approval
    assert ledger.execute("P-1", "t", 3, {}).transaction_id == "TX-1"
    assert policy.get_policy("hardship", AS_OF) == []
    approvals.record(
        Approval(
            approval_id="A-1", proposal_id="P-1", approver="compliance", decision=Decision.HOLD
        )
    )


# ---------- #93: the token was bound to the proposal hash only ----------
# Found by /code-review on PR #92 (spec). GR-18: an approval is bound to that exact proposal.
def test_issue_93_identical_proposals_get_different_tokens() -> None:
    h = _proposal().hash  # two proposals with the same figures, customer and as-of date
    assert approval_token("P-1", h, b"s") != approval_token("P-2", h, b"s")
    assert approval_token("P-1", h, b"s") == approval_token("P-1", h, b"s")


# ---------- #94: the status machine could not escalate from quoted or approved ----------
# Found by /code-review on PR #92 (spec): BH-B3-05 and the FR-26 kill switch after approval.
@pytest.mark.parametrize("before", [ProposalStatus.QUOTED, ProposalStatus.APPROVED])
def test_issue_94_quoted_and_approved_proposals_can_go_to_a_human(before: ProposalStatus) -> None:
    assert ProposalStatus.ESCALATED in PROPOSAL_TRANSITIONS[before]


# ---------- review follow-ups on PR #92: the rules as code, not docstrings ----------
def test_check_transition_allows_only_the_table() -> None:
    check_transition(ProposalStatus.QUOTED, ProposalStatus.CONFIRMED)
    with pytest.raises(ValueError):
        check_transition(ProposalStatus.QUOTED, ProposalStatus.EXECUTED)
    with pytest.raises(ValueError):
        check_transition(ProposalStatus.EXECUTED, ProposalStatus.EXECUTED)


def test_check_confirmation_accepts_a_later_yes_for_the_quoted_amount() -> None:
    check_confirmation(
        _proposal(), Confirmation(proposal_id="P-1", amount_cents=2_000_000, turn=2), "CV1"
    )


@pytest.mark.parametrize(
    ("confirmation", "conversation_id"),
    [
        (Confirmation(proposal_id="P-1", amount_cents=2_200_000, turn=2), "CV1"),  # BH-B3-02
        (Confirmation(proposal_id="P-1", amount_cents=2_000_000, turn=1), "CV1"),  # same turn
        (Confirmation(proposal_id="P-2", amount_cents=2_000_000, turn=2), "CV1"),  # other proposal
        (Confirmation(proposal_id="P-1", amount_cents=2_000_000, turn=2), "CV2"),  # other session
    ],
)
def test_check_confirmation_refuses_anything_else(
    confirmation: Confirmation, conversation_id: str
) -> None:
    with pytest.raises(ValueError):
        check_confirmation(_proposal(), confirmation, conversation_id)


def test_every_decision_has_its_effect_on_the_proposal() -> None:
    assert set(DECISION_MOVES) == set(Decision)
    assert DECISION_MOVES[Decision.APPROVE] is ProposalStatus.APPROVED
    assert DECISION_MOVES[Decision.HOLD] is ProposalStatus.ESCALATED  # FR-12: a human case
    assert DECISION_MOVES[Decision.ESCALATE] is ProposalStatus.ESCALATED
    assert DECISION_MOVES[Decision.REJECT] is ProposalStatus.VOIDED
    assert DECISION_MOVES[Decision.REQUEST_INFO] is None  # stays with the human


def test_execution_refusal_reasons_are_exactly_these() -> None:
    assert {r.value for r in ExecutionRefusedReason} == {
        "unknown_proposal",
        "not_approved",
        "token_invalid",
        "hash_changed",
        "execution_disabled",
    }
