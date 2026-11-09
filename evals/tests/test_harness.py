"""Tests for evals.run and evals.score with a fake DeskRunner (issue #41). No network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from contracts.messages import Citation
from contracts.outcomes import Outcome
from contracts.ports import TurnResult
from contracts.tools import Step
from evals import run as run_mod
from evals.score import FAIL, NA, PASS, Restricted, case_status, score_case

DOB, LAST4 = "1958-03-14", "7823"


def turn(text: str = "ok", outcome: Outcome = Outcome.ANSWERED, **kw: Any) -> TurnResult:
    return TurnResult(conversation_id="c1", turn=1, reply_text=text, outcome=outcome, **kw)


class FakeRunner:
    def __init__(self, replies: list[TurnResult] | None = None) -> None:
        self.replies = replies or []
        self.sent: list[tuple[str, str]] = []
        self.started: list[str | None] = []

    def start(self, customer_id: str | None) -> str:
        self.started.append(customer_id)
        return "c1"

    def send(self, conversation_id: str, text: str) -> TurnResult:
        self.sent.append((conversation_id, text))
        return self.replies.pop(0) if self.replies else turn()


def test_pass() -> None:
    t = turn(
        "The charge is 3%. Your net is $19, 324.70",
        citations=(Citation(doc_id="fee_schedule", version=1, section="s"),),
        steps=(Step.SEARCH_KB, Step.QUOTE),
    )
    expect = {
        "outcome": "ANSWERED",
        "contains": ["3%"],
        "numbers": ["19,324.70"],
        "cites": ["fee_schedule"],
        "tools": ["search_kb"],
        "not_tools": ["execute"],
        "order": ["search_kb", "quote"],
        "executed": False,
    }
    s = score_case(expect, [t])
    assert s.verdict == PASS
    assert s.not_checked == ("executed",)


@pytest.mark.parametrize(
    ("key", "value", "result"),
    [
        ("outcome", "EXECUTED", turn()),
        ("final_outcome", "EXECUTED", turn()),
        ("contains", ["zebra"], turn()),
        ("not_contains", ["ok"], turn()),
        ("numbers", ["1,000.00"], turn()),
        ("cites", ["faq"], turn()),
        ("cites_any", ["faq"], turn()),
        ("tools", ["quote"], turn()),
        ("not_tools", ["quote"], turn(steps=(Step.QUOTE,))),
        ("order", ["quote", "execute"], turn(steps=(Step.EXECUTE, Step.QUOTE))),
        ("forbid_claims", ["advice"], turn("I recommend you withdraw it.")),
    ],
)
def test_fails_naming_key(key: str, value: Any, result: TurnResult) -> None:
    s = score_case({key: value}, [result])
    assert (s.verdict, s.failed_key) == (FAIL, key)


def test_provider_error_is_na() -> None:
    s = score_case({"outcome": "EXECUTED"}, [turn(provider_error=True)])
    assert s.verdict == NA


def test_restricted_value_in_reply_fails() -> None:
    r = Restricted(frozenset({DOB}), frozenset({LAST4}))
    assert score_case({}, [turn(f"Born {DOB}")], r).failed_key == "restricted_field"
    assert score_case({}, [turn("Balance $87,450.62 or 17,823")], r).verdict == PASS
    assert score_case({}, [turn("digits 7823")], r).verdict == FAIL


def test_case_status() -> None:
    assert case_status([PASS, PASS, PASS]) == PASS
    assert case_status([PASS, FAIL]) == "flaky"
    assert case_status([FAIL, FAIL]) == FAIL
    assert case_status([PASS, NA]) == PASS
    assert case_status([NA]) == NA


def write_golden(tmp: Path, golden: str, behavioural: str) -> Path:
    (tmp / "golden.yaml").write_text(golden)
    (tmp / "behavioural.yaml").write_text(behavioural)
    return tmp


GOLDEN = """
cases:
  - id: G-B1-01
    bullet: B1
    customer: null
    ask: "hi"
    expect: {outcome: ANSWERED, contains: ["ok"], cites_version: current}
  - id: G-B2-01
    bullet: B2
    customer: null
    ask: "later"
    expect: {outcome: ANSWERED}
"""
BEHAVIOURAL = """
cases:
  - id: BH-B1-01
    bullet: B1
    customer: SPR-1001
    session: {gate_b_passed: true}
    turns:
      - user: "withdraw"
      - user: "yes"
    expect: {final_outcome: EXECUTED}
  - id: BH-B1-02
    bullet: B1
    status: pending_data
    customer: null
    ask: "x"
    expect: {outcome: ANSWERED}
"""


def run(tmp_path: Path, runner: FakeRunner, **kw: Any) -> dict[str, Any]:
    write_golden(tmp_path, GOLDEN, BEHAVIOURAL)
    return run_mod.run_suite(runner, suite="all", bullet="B1", golden_dir=tmp_path, **kw)


def test_run_suite_skips_pending_and_later_bullets(tmp_path: Path) -> None:
    runner = FakeRunner()
    res = run(tmp_path, runner)
    ran = {r["case_id"] for r in res["records"]}
    assert ran == {"G-B1-01", "BH-B1-01"}
    reasons = {n["case_id"]: n["reason"] for n in res["not_run"]}
    assert reasons["BH-B1-02"] == "pending_data"
    assert "G-B2-01" in reasons
    assert res["not_checked"] == {"G-B1-01": ["cites_version"]}


def test_gate_b_sends_unscored_verification_without_leaking(tmp_path: Path) -> None:
    runner = FakeRunner([turn("verified"), turn("quote"), turn("done", Outcome.EXECUTED)])
    # first case in file order is golden: give it a reply first
    runner.replies.insert(0, turn("ok"))
    res = run(tmp_path, runner)
    bh = next(r for r in res["records"] if r["case_id"] == "BH-B1-01")
    assert bh["verdict"] == PASS
    assert len(bh["trace"]) == 2  # verification turn not in the trace
    verification = [t for _, t in runner.sent if "date of birth" in t]
    assert len(verification) == 1
    assert DOB in verification[0]
    assert runner.started == [None, "SPR-1001"]
    out_json, out_md = run_mod.write_results(res, tmp_path / "out")
    for p in (out_json, out_md):
        text = p.read_text()
        assert DOB not in text
        assert f'"{LAST4}"' not in text


def test_leaked_value_fails_and_is_redacted(tmp_path: Path) -> None:
    res = run(tmp_path, FakeRunner([turn(f"you were born {DOB}, ok")]))
    rec = res["records"][0]
    assert (rec["verdict"], rec["failed_key"]) == (FAIL, "restricted_field")
    out_json, _ = run_mod.write_results(res, tmp_path / "out")
    assert DOB not in out_json.read_text()


def test_provider_error_in_setup_is_na(tmp_path: Path) -> None:
    runner = FakeRunner([turn("ok"), turn(provider_error=True)])
    res = run(tmp_path, runner)
    bh = next(r for r in res["records"] if r["case_id"] == "BH-B1-01")
    assert bh["verdict"] == NA


def test_repeat_and_scorecard(tmp_path: Path) -> None:
    res = run(tmp_path, FakeRunner(), repeat=3)
    assert len(res["records"]) == 6
    _, md = run_mod.write_results(res, tmp_path / "out")
    text = md.read_text()
    assert "Not yet run" in text and "G-B2-01" in text and "Not checked yet" in text


def test_main_writes_files_and_score_cli(tmp_path: Path) -> None:
    from evals import score

    rc = run_mod.main(["--suite", "golden", "--bullet", "B1", "--out", str(tmp_path)], FakeRunner())
    assert rc == 0
    js = next(tmp_path.glob("*.json"))
    js.with_suffix(".md").unlink()
    assert score.main([str(js)]) == 0
    assert js.with_suffix(".md").exists()
    json.loads(js.read_text())


def test_main_without_runner_errors() -> None:
    with pytest.raises(SystemExit):
        run_mod.main(["--suite", "golden"])
