"""Contract tests for 0.6.0 (issue #100, ADR 0007): login, guest sessions and the step-up.

0.6.0 is additive. The rules that tighten (an account view needs a login, the step-up needs a login,
`start` for guests only) come in the next version, once the lanes comply (#102, #103).
"""

import inspect
from datetime import date

import pytest
from pydantic import ValidationError

from contracts import CONTRACTS_VERSION
from contracts.messages import AccountStatus, AccountView, AgeBand
from contracts.outcomes import Outcome
from contracts.ports import (
    DeskRunner,
    LoginDeskRunner,
    LoginRefused,
    PasswordCheck,
    TurnResult,
)
from contracts.state import (
    SESSION_FIELD_WRITERS,
    ContractViolation,
    ConversationState,
    Session,
    Versions,
    check_write,
)
from contracts.tools import Node

AS_OF = date(2024, 12, 1)
LOGGED_IN = Session(customer_id="SPR-1001", gate_a_trusted=True, authenticated=True)


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


def _state(session: Session, view: AccountView | None = None) -> ConversationState:
    return ConversationState(
        conversation_id="CV1",
        as_of=AS_OF,
        session=session,
        versions=Versions(contracts=CONTRACTS_VERSION),
        account_view=view,
    )


def test_version_is_current() -> None:
    # 0.6.1 (#89) adds CaseReason.WITHDRAWAL_REVIEW, and 0.6.2 the B4 reviewer port, on top of
    # this file's 0.6.0 ports; 0.6.3 (#172) adds LoginDeskRunner.account;
    # 0.6.4 (#176) adds AccountView.contract_start_date.
    assert CONTRACTS_VERSION == "0.6.4"


# ---------- the session records the login ----------
def test_a_session_starts_unauthenticated() -> None:
    assert Session().authenticated is False


def test_only_intake_writes_authenticated() -> None:
    assert SESSION_FIELD_WRITERS["authenticated"] is Node.INTAKE
    check_write(Node.INTAKE, "session.authenticated")
    with pytest.raises(ContractViolation):
        check_write(Node.IDENTITY_GATE, "session.authenticated")


def test_a_login_needs_a_customer() -> None:
    with pytest.raises(ValidationError):
        Session(authenticated=True)


# ---------- ADR 0007: a login and Gate A show the account; no step-up needed ----------
def test_a_logged_in_trusted_customer_may_see_their_account() -> None:
    _state(LOGGED_IN, _view())


def test_a_logged_in_untrusted_customer_may_not() -> None:
    untrusted = Session(customer_id="SPR-1002", gate_a_trusted=False, authenticated=True)
    with pytest.raises(ValidationError):  # Raymond: Gate A still turns him away
        _state(untrusted, _view("SPR-1002"))


def test_a_logged_in_customer_sees_only_their_own_account() -> None:
    with pytest.raises(ValidationError):
        _state(LOGGED_IN, _view("SPR-1004"))


def test_an_unauthenticated_unverified_session_still_may_not() -> None:
    with pytest.raises(ValidationError):
        _state(Session(customer_id="SPR-1001", gate_a_trusted=True), _view())


# ---------- the login port ----------
def test_password_check_is_a_boolean_port() -> None:
    sig = inspect.signature(PasswordCheck.check_password)
    assert list(sig.parameters) == ["self", "customer_id", "password"]
    assert sig.return_annotation is bool


def test_a_refused_login_does_not_say_which_part_was_wrong() -> None:
    # One reason only, so the login page can't be used to find which customer IDs exist.
    assert set(LoginRefused.model_fields) == {"reason"}
    assert LoginRefused().reason == "invalid_credentials"
    with pytest.raises(ValidationError):
        LoginRefused.model_validate({"reason": "unknown_customer"})


def test_the_ui_is_told_when_to_show_the_step_up_form() -> None:
    result = TurnResult(conversation_id="CV1", turn=1, reply_text="", outcome=Outcome.ANSWERED)
    assert result.step_up_required is False


def test_the_login_runner_extends_the_desk_runner() -> None:
    assert DeskRunner in LoginDeskRunner.__mro__
    login = inspect.signature(LoginDeskRunner.login)
    assert list(login.parameters) == ["self", "customer_id", "password"]
    step_up = inspect.signature(LoginDeskRunner.step_up)
    # Typed values, straight from the form: never turn text (ADR 0007).
    assert list(step_up.parameters) == ["self", "conversation_id", "dob", "last4"]
    assert step_up.parameters["dob"].annotation is date
    assert step_up.return_annotation is TurnResult


class _FakeLoginRunner:
    def start(self, customer_id: str | None) -> str:
        return "CV-guest"

    def send(self, conversation_id: str, text: str) -> TurnResult:
        return TurnResult(
            conversation_id=conversation_id, turn=1, reply_text="", outcome=Outcome.ANSWERED
        )

    def login(self, customer_id: str, password: str) -> str | LoginRefused:
        return "CV1" if password == "right" else LoginRefused()

    def account(self, conversation_id: str) -> AccountView | None:
        return None

    def step_up(self, conversation_id: str, dob: date, last4: str) -> TurnResult:
        return TurnResult(
            conversation_id=conversation_id, turn=2, reply_text="", outcome=Outcome.ANSWERED
        )


class _FakePasswords:
    def check_password(self, customer_id: str, password: str) -> bool:
        return password == "right"


def test_fakes_conform_to_the_login_ports() -> None:
    runner: LoginDeskRunner = _FakeLoginRunner()
    passwords: PasswordCheck = _FakePasswords()
    assert runner.login("SPR-1001", "right") == "CV1"
    assert isinstance(runner.login("SPR-1001", "wrong"), LoginRefused)
    assert runner.step_up("CV1", date(1958, 3, 14), "7823").turn == 2
    assert runner.account("CV1") is None  # 0.6.3 (#172)
    assert not passwords.check_password("SPR-1001", "wrong")


# ---------- #107: a logged-in but locked session could hold an account view ----------
# Found by /code-review on PR #106 (spec): the login branch dropped the lock (D-08, FR-04).
def test_issue_107_a_locked_session_never_sees_the_account() -> None:
    locked = Session(
        customer_id="SPR-1001",
        gate_a_trusted=True,
        authenticated=True,
        failed_attempts=3,
        locked=True,
    )
    with pytest.raises(ValidationError):
        _state(locked, _view())


# ---------- #108: the contract allowed a passed step-up on a locked session ----------
# Found by /code-review on PR #106 (spec): ADR 0007 section 4, the right answer after a lock.
def test_issue_108_a_locked_session_cannot_have_passed_the_step_up() -> None:
    with pytest.raises(ValidationError):
        Session(
            customer_id="SPR-1001",
            gate_a_trusted=True,
            authenticated=True,
            gate_b_passed=True,
            failed_attempts=3,
            locked=True,
        )


def test_issue_108_passed_and_verified_need_an_unlocked_session() -> None:
    from contracts.state import GATE_REQUIRES, GateResult

    locked_only = Session.model_construct(
        customer_id="SPR-1001", gate_a_trusted=True, gate_b_passed=True, locked=True
    )  # built past the validator, to test the gate table on its own
    assert not GATE_REQUIRES[GateResult.PASSED](locked_only)
    assert not GATE_REQUIRES[GateResult.VERIFIED](locked_only)


# ---------- review follow-ups on PR #106 ----------
def test_logged_in_is_the_gate_result_for_a_login_without_a_step_up() -> None:
    from contracts.state import GATE_REQUIRES, GateResult

    ok = GATE_REQUIRES[GateResult.LOGGED_IN]
    assert ok(LOGGED_IN)
    assert not ok(Session(customer_id="SPR-1001", gate_a_trusted=True))  # no login
    assert not ok(Session(customer_id="SPR-1002", authenticated=True))  # Gate A fails
    assert not ok(
        Session(
            customer_id="SPR-1001",
            gate_a_trusted=True,
            authenticated=True,
            failed_attempts=3,
            locked=True,
        )
    )
    stepped_up = LOGGED_IN.model_copy(update={"gate_b_passed": True})
    assert not ok(stepped_up)  # that is VERIFIED / PASSED
    ConversationState(
        conversation_id="CV1",
        as_of=AS_OF,
        session=LOGGED_IN,
        versions=Versions(contracts=CONTRACTS_VERSION),
        gate=GateResult.LOGGED_IN,
        account_view=_view(),
    )


def test_a_step_up_is_pending_only_after_a_confirmed_yes_without_one() -> None:
    from contracts.messages import Confirmation
    from contracts.state import step_up_pending

    yes = Confirmation(proposal_id="P-1", amount_cents=2_000_000, turn=2)
    base = _state(LOGGED_IN)
    assert not step_up_pending(base)  # nothing to continue
    assert step_up_pending(base.model_copy(update={"confirmation": yes}))
    passed = LOGGED_IN.model_copy(update={"gate_b_passed": True})
    assert not step_up_pending(_state(passed).model_copy(update={"confirmation": yes}))
    locked = LOGGED_IN.model_copy(update={"failed_attempts": 3, "locked": True})
    assert not step_up_pending(_state(locked).model_copy(update={"confirmation": yes}))
