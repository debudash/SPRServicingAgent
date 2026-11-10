"""The identity flow over the real SQLite stores the wiring builds (offline, scripted).

Issue #59 built it for the chat challenge; issue #102 (ADR 0007) moves it to the login and the
step-up, with the demo passwords from data/demo_logins.json.
"""

from datetime import date
from pathlib import Path

import pytest

from agents.runner import GraphDeskRunner
from agents.testing import ScriptedChatModel, put_pending_confirmation
from agents.wiring import build_stores, customer_ids, open_desk_db
from contracts.messages import Intent, IntentKind
from contracts.outcomes import Outcome
from contracts.ports import LoginRefused
from contracts.tools import Role, Step

from .test_graph import FakeSearch, MemoryAudit


def _runner(tmp_path: Path, *kinds: IntentKind) -> GraphDeskRunner:
    return GraphDeskRunner(
        search=FakeSearch([]),
        audit=MemoryAudit(),
        models={
            Role.CONCIERGE: ScriptedChatModel([Intent(kind=k) for k in kinds]),
            Role.KNOWLEDGE: ScriptedChatModel(),
        },
        clock=lambda: date(2024, 12, 1),
        stores=build_stores(open_desk_db(tmp_path / "desk.db")),
    )


def _login(runner: GraphDeskRunner, customer_id: str, password: str) -> str:
    conv = runner.login(customer_id, password)
    assert isinstance(conv, str)
    return conv


def test_bh_b2_02_login_then_balance_over_the_real_stores(tmp_path: Path) -> None:
    runner = _runner(tmp_path, IntentKind.ACCOUNT_INFO)
    r = runner.send(_login(runner, "SPR-1001", "margaret-demo"), "What's my balance?")
    assert r.outcome is Outcome.ANSWERED
    assert r.steps == (Step.GET_ACCOUNT,)
    assert "$87,450.62" in r.reply_text and "$8,745.06" in r.reply_text


def test_a_wrong_password_is_refused_over_the_real_stores(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    assert runner.login("SPR-1001", "raymond-demo") == LoginRefused()
    assert runner.login("SPR-9999", "margaret-demo") == LoginRefused()


def test_bh_b2_01_three_failed_step_ups_open_a_stored_case(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    conv = _login(runner, "SPR-1001", "margaret-demo")
    put_pending_confirmation(runner, conv)
    wrong = [(date(1960, 1, 1), "1111"), (date(1958, 3, 15), "7832"), (date(1958, 3, 14), "0000")]
    for dob, last4 in wrong:
        r = runner.step_up(conv, dob, last4)
    assert r.outcome is Outcome.NOT_PERMITTED and r.reference is not None
    assert Step.CREATE_CASE in r.steps


def test_the_right_step_up_passes_over_the_real_stores(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    conv = _login(runner, "SPR-1001", "margaret-demo")
    put_pending_confirmation(runner, conv)
    r = runner.step_up(conv, date(1958, 3, 14), "7823")
    assert r.outcome is Outcome.ANSWERED and r.steps == (Step.VERIFY_IDENTITY,)


def test_untrusted_account_over_the_real_stores(tmp_path: Path) -> None:
    runner = _runner(tmp_path, IntentKind.ACCOUNT_INFO)
    r = runner.send(_login(runner, "SPR-1002", "raymond-demo"), "What's my current balance?")
    assert r.outcome is Outcome.NOT_PERMITTED and "1-800-555-0192" in r.reply_text
    assert "42,100" not in r.reply_text


def test_demo_logins_are_seeded_only_when_switched_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DESK_DEMO_LOGINS", "false")
    runner = _runner(tmp_path)
    assert runner.login("SPR-1001", "margaret-demo") == LoginRefused()


def test_picker_lists_the_starter_kit_customers() -> None:
    assert customer_ids() == ["SPR-1001", "SPR-1002", "SPR-1003", "SPR-1004"]
