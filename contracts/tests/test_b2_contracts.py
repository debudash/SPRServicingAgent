"""Contract tests for the B2 additions (issue #56): identity, account and case ports."""

import inspect
from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from contracts import CONTRACTS_VERSION
from contracts.messages import (
    AccountStatus,
    AccountView,
    AgeBand,
    CasePacket,
    CaseReason,
    IntentKind,
    Quote,
    ThresholdTier,
)
from contracts.ports import AccountStore, CaseStore, IdentityCheck
from contracts.state import (
    FIELD_WRITERS,
    ContractViolation,
    ConversationState,
    GateResult,
    Session,
    Versions,
    check_write,
)
from contracts.tools import Node

AS_OF = date(2024, 12, 1)


def _view(customer_id: str = "SPR-1001") -> AccountView:
    return AccountView(
        customer_id=customer_id,
        account_status=AccountStatus.ACTIVE,
        contract_year=3,
        age_band=AgeBand.FROM_59_5_TO_79,
        balance_cents=8_745_062,
        allowance_remaining_cents=874_506,
        withdrawals_this_year=0,
    )


def _state(session: Session, **fields: Any) -> ConversationState:
    return ConversationState(
        conversation_id="CV1",
        as_of=AS_OF,
        session=session,
        versions=Versions(contracts=CONTRACTS_VERSION),
        **fields,
    )


VERIFIED = Session(customer_id="SPR-1001", gate_a_trusted=True, gate_b_passed=True)
UNVERIFIED = Session(customer_id="SPR-1001", gate_a_trusted=True)


# ---------- intents (NG-05, NG-08) ----------
def test_intents_for_other_accounts_and_restricted_fields_exist() -> None:
    assert IntentKind("other_account") is IntentKind.OTHER_ACCOUNT
    assert IntentKind("restricted_info") is IntentKind.RESTRICTED_INFO


# ---------- the gate result is identity_gate's alone ----------
def test_only_identity_gate_writes_the_gate_result() -> None:
    assert FIELD_WRITERS["gate"] is Node.IDENTITY_GATE
    check_write(Node.IDENTITY_GATE, "gate")
    for node in Node:
        if node is not Node.IDENTITY_GATE:
            with pytest.raises(ContractViolation):
                check_write(node, "gate")


@pytest.mark.parametrize("gate", [GateResult.PASSED, GateResult.VERIFIED])
def test_a_passing_gate_needs_gate_b_in_the_session(gate: GateResult) -> None:
    _state(VERIFIED, gate=gate)
    with pytest.raises(ValidationError):
        _state(UNVERIFIED, gate=gate)


@pytest.mark.parametrize("gate", [GateResult.LOCKED, GateResult.LOCKED_NOW])
def test_a_locked_gate_needs_a_locked_session(gate: GateResult) -> None:
    locked = Session(customer_id="SPR-1001", gate_a_trusted=True, failed_attempts=3, locked=True)
    _state(locked, gate=gate)
    with pytest.raises(ValidationError):
        _state(UNVERIFIED, gate=gate)


def test_an_untrusted_gate_needs_an_untrusted_session() -> None:
    _state(Session(customer_id="SPR-1002"), gate=GateResult.UNTRUSTED)
    with pytest.raises(ValidationError):
        _state(UNVERIFIED, gate=GateResult.UNTRUSTED)


# ---------- FR-02 and NG-05 as a property of the state ----------
def test_an_account_view_needs_both_gates() -> None:
    _state(VERIFIED, account_view=_view())
    with pytest.raises(ValidationError):
        _state(UNVERIFIED, account_view=_view())
    with pytest.raises(ValidationError):
        _state(Session(), account_view=_view())


def test_an_account_view_must_be_the_bound_customers() -> None:
    with pytest.raises(ValidationError):
        _state(VERIFIED, account_view=_view("SPR-1004"))


# ---------- cases (FR-04, D-08, D-09) ----------
def test_a_case_packet_says_why_it_was_opened() -> None:
    assert {r.value for r in CaseReason} >= {"locked", "third_party"}
    packet = CasePacket(
        case_id="CASE-1",
        conversation_id="CV1",
        customer_id="SPR-1001",
        opened_for=CaseReason.LOCKED,
        request_summary="Session locked after three failed identity challenges.",
        quote=None,
        excerpt="[DOB] and [SSN-4]",
        recommendation="Contact the customer through a verified channel.",
    )
    assert packet.opened_for is CaseReason.LOCKED
    with pytest.raises(ValidationError):
        CasePacket.model_validate({**packet.model_dump(), "opened_for": "because"})


# ---------- ports ----------
def test_identity_check_takes_candidates_and_returns_only_a_boolean() -> None:
    sig = inspect.signature(IdentityCheck.check_challenge)
    assert list(sig.parameters) == ["self", "customer_id", "dob", "last4"]
    assert sig.return_annotation is bool


class _FakeAccounts:
    def gate_a(self, customer_id: str) -> bool:
        return customer_id == "SPR-1001"

    def view(self, customer_id: str, as_of: date) -> AccountView:
        return _view(customer_id)


class _FakeIdentity:
    def check_challenge(self, customer_id: str, dob: date, last4: str) -> bool:
        return False


class _FakeCases:
    def __init__(self) -> None:
        self.opened: list[CasePacket] = []

    def open(self, packet: CasePacket) -> None:
        self.opened.append(packet)


def test_fakes_conform_to_the_b2_ports() -> None:
    accounts: AccountStore = _FakeAccounts()
    identity: IdentityCheck = _FakeIdentity()
    fake_cases = _FakeCases()
    cases: CaseStore = fake_cases
    assert accounts.gate_a("SPR-1001") and not accounts.gate_a("SPR-1002")
    assert accounts.view("SPR-1001", AS_OF).customer_id == "SPR-1001"
    assert not identity.check_challenge("SPR-1001", date(1958, 3, 14), "7823")
    packet = CasePacket(
        case_id="CASE-2",
        conversation_id="CV1",
        customer_id="SPR-1003",
        opened_for=CaseReason.THIRD_PARTY,
        request_summary="A family member asked to withdraw for the customer.",
        quote=None,
        excerpt="I'm Linda's son",
        recommendation="Contact the owner directly.",
    )
    cases.open(packet)
    assert fake_cases.opened == [packet]


# ---------- #62: gate results the session contradicts were accepted ----------
# Found by /code-review on PR #61 (both axes): only four of the eight values had a rule.
ANON = Session()
UNTRUSTED = Session(customer_id="SPR-1002")
FAILED_ONCE = Session(customer_id="SPR-1001", gate_a_trusted=True, failed_attempts=1)
LOCKED = Session(customer_id="SPR-1001", gate_a_trusted=True, failed_attempts=3, locked=True)


@pytest.mark.parametrize(
    ("gate", "session"),
    [
        (GateResult.NO_CUSTOMER, UNVERIFIED),
        (GateResult.UNTRUSTED, ANON),
        (GateResult.ASK, VERIFIED),
        (GateResult.ASK, LOCKED),
        (GateResult.ASK, UNTRUSTED),
        (GateResult.FAILED, UNVERIFIED),  # no failed attempt recorded
        (GateResult.FAILED, LOCKED),
        (GateResult.FAILED, VERIFIED),
    ],
)
def test_issue_62_a_gate_the_session_contradicts_is_refused(
    gate: GateResult, session: Session
) -> None:
    with pytest.raises(ValidationError):
        _state(session, gate=gate)


@pytest.mark.parametrize(
    ("gate", "session"),
    [
        (GateResult.NO_CUSTOMER, ANON),
        (GateResult.UNTRUSTED, UNTRUSTED),
        (GateResult.ASK, UNVERIFIED),
        (GateResult.ASK, FAILED_ONCE),
        (GateResult.FAILED, FAILED_ONCE),
        (GateResult.LOCKED, LOCKED),
        (GateResult.LOCKED_NOW, LOCKED),
        (GateResult.PASSED, VERIFIED),
        (GateResult.VERIFIED, VERIFIED),
    ],
)
def test_issue_62_a_consistent_gate_is_accepted(gate: GateResult, session: Session) -> None:
    _state(session, gate=gate)


def test_issue_62_every_gate_result_has_a_rule() -> None:
    from contracts.state import GATE_REQUIRES

    assert set(GATE_REQUIRES) == set(GateResult)


# ---------- #80: every case names its customer (owner decision) ----------
@pytest.mark.parametrize("customer_id", [None, ""])
def test_issue_80_a_case_packet_needs_a_customer(customer_id: str | None) -> None:
    with pytest.raises(ValidationError):
        CasePacket(
            case_id="CASE-3",
            conversation_id="CV1",
            customer_id=customer_id,
            opened_for=CaseReason.THIRD_PARTY,
            request_summary="Someone asked about an account they did not identify.",
            quote=None,
            excerpt="what's my mum's balance",
            recommendation="None: no account to act on.",
        )


# ---------- 0.6.1 (#89): a withdrawal review carries its quote ----------
def _review_packet(quote: Quote | None) -> CasePacket:
    return CasePacket(
        case_id="CASE-1",
        conversation_id="CV1",
        customer_id="SPR-1001",
        opened_for=CaseReason.WITHDRAWAL_REVIEW,
        request_summary="Withdrawal over $25,000.",
        quote=quote,
        excerpt="withdraw $30,000",
        recommendation="Review the withdrawal.",
    )


def test_a_withdrawal_review_carries_its_quote() -> None:
    quote = Quote(
        amount_cents=3_000_000,
        free_cents=874_506,
        excess_cents=2_125_494,
        rate_bp=600,
        charge_cents=127_530,
        net_cents=2_872_470,
        contract_year=3,
        threshold_tier=ThresholdTier.HUMAN,
        irs_notice=False,
    )
    assert _review_packet(quote).quote == quote
    with pytest.raises(ValidationError):
        _review_packet(None)
