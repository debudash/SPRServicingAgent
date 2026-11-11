"""#104: the behaviour demo's nine scenarios pass offline, show no restricted value, and the page
opens from the login page and runs one."""

import json
import re
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agents.demo.__main__ import main as demo_main
from agents.demo.scenarios import SCENARIOS, ScenarioRun, as_text, run_all

from .test_ui import APP, FakeRunner

ACCOUNTS = Path(__file__).parents[2] / "problemstmt" / "spr_starter_kit" / "data" / "accounts.json"


def _restricted() -> list[re.Pattern[str]]:
    """Every customer's date of birth (in the usual spellings) and SSN last four as a number."""
    patterns: list[re.Pattern[str]] = []
    for a in json.loads(ACCOUNTS.read_text("utf-8"))["accounts"]:
        dob = date.fromisoformat(a["dob"])
        for spelling in (
            dob.isoformat(),
            dob.strftime("%m/%d/%Y"),
            f"{dob:%B} {dob.day}, {dob.year}",
        ):
            patterns.append(re.compile(re.escape(spelling)))
        # As a number of its own: random hex IDs may contain the digits by chance.
        patterns.append(re.compile(rf"(?<![0-9A-Za-z]){a['last4_ssn']}(?![0-9A-Za-z])"))
    return patterns


@pytest.fixture(scope="module")
def runs() -> list[ScenarioRun]:
    return run_all()


def test_there_are_nine_scenarios() -> None:
    assert [s.number for s in SCENARIOS] == list(range(1, 10))


def test_every_scenario_passes_offline(runs: list[ScenarioRun]) -> None:
    assert [(r.scenario.number, r.failures) for r in runs if not r.passed] == []


def test_only_the_two_approved_withdrawals_move_money(runs: list[ScenarioRun]) -> None:
    moved = {r.scenario.number: [row.approved_by for row in r.ledger] for r in runs if r.ledger}
    assert moved == {4: ["compliance"], 7: ["human:demo-reviewer"]}


def test_no_restricted_value_appears_in_any_scenario(runs: list[ScenarioRun]) -> None:
    shown = "\n".join(as_text(r) for r in runs)
    assert "Identity check submitted" in shown
    for pattern in _restricted():
        assert not pattern.search(shown), pattern.pattern


def test_the_terminal_run_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert demo_main([]) == 0
    out = capsys.readouterr().out
    assert out.count("PASS") == 9 and "FAIL" not in out


def test_the_page_opens_from_the_login_page_and_runs_a_scenario() -> None:
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["runner"] = FakeRunner()
    at.run()
    at.button(key="open_demo").click().run()
    assert not at.exception
    assert at.selectbox(key="demo_scenario").options[0] == "1. A cited product answer"
    at.selectbox(key="demo_scenario").select("4. The full money path").run()
    at.button(key="demo_run").click().run()
    assert not at.exception
    page = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "**PASS**" in page and "EXECUTED" in page
    assert "intake → identity_gate → rules → compliance → approval → execute → respond" in page
    assert "Identity check submitted" in page
    for pattern in _restricted():
        assert not pattern.search(page), pattern.pattern
    at.button(key="close_demo").click().run()
    assert at.selectbox(key="login_customer")  # back on the login page


def test_the_demo_opens_without_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert any("ANTHROPIC_API_KEY" in e.value for e in at.error)
    at.button(key="open_demo").click().run()
    assert not at.exception
    assert at.button(key="demo_run")
