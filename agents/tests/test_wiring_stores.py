"""Issue #59: the B2 flow over the real SQLite stores the wiring builds (offline, scripted)."""

from datetime import date
from pathlib import Path

from agents.runner import GraphDeskRunner
from agents.testing import ScriptedChatModel
from agents.wiring import build_stores, customer_ids, open_desk_db
from contracts.messages import Intent, IntentKind
from contracts.outcomes import Outcome
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
        **build_stores(open_desk_db(tmp_path / "desk.db")),
    )


def test_bh_b2_02_over_the_real_stores(tmp_path: Path) -> None:
    runner = _runner(tmp_path, IntentKind.ACCOUNT_INFO, IntentKind.VERIFY)
    conv = runner.start("SPR-1001")
    runner.send(conv, "What's my balance?")
    r = runner.send(conv, "1958-03-14, and the last four are 7823.")
    assert r.outcome is Outcome.ANSWERED
    assert r.steps == (Step.VERIFY_IDENTITY, Step.GET_ACCOUNT)
    assert "$87,450.62" in r.reply_text and "$8,745.06" in r.reply_text


def test_bh_b2_01_lock_opens_a_stored_case(tmp_path: Path) -> None:
    runner = _runner(tmp_path, *[IntentKind.VERIFY] * 3)
    conv = runner.start("SPR-1001")
    for text in ("1960-01-01 and 1111", "1958-03-15 and 7832", "1958-03-14 and 0000"):
        r = runner.send(conv, text)
    assert r.outcome is Outcome.NOT_PERMITTED and r.reference is not None
    assert Step.CREATE_CASE in r.steps


def test_untrusted_account_over_the_real_stores(tmp_path: Path) -> None:
    runner = _runner(tmp_path, IntentKind.ACCOUNT_INFO)
    r = runner.send(runner.start("SPR-1002"), "What's my current balance?")
    assert r.outcome is Outcome.NOT_PERMITTED and "1-800-555-0192" in r.reply_text
    assert "42,100" not in r.reply_text


def test_picker_lists_the_starter_kit_customers() -> None:
    assert customer_ids() == ["SPR-1001", "SPR-1002", "SPR-1003", "SPR-1004"]
