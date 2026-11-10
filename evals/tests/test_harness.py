"""Tests for evals.run and evals.score with a fake DeskRunner (issue #41). No network."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from contracts.messages import Citation
from contracts.outcomes import Outcome
from contracts.ports import LoginRefused, TurnResult
from contracts.tools import Step
from evals import run as run_mod
from evals.score import FAIL, NA, PASS, Restricted, case_status, score_case

DOB, LAST4 = "1958-03-14", "7823"


def turn(text: str = "ok", outcome: Outcome = Outcome.ANSWERED, **kw: Any) -> TurnResult:
    return TurnResult(conversation_id="c1", turn=1, reply_text=text, outcome=outcome, **kw)


class FakeRunner:
    """A LoginDeskRunner fake: `replies` answer send and step_up in order."""

    def __init__(self, replies: list[TurnResult] | None = None) -> None:
        self.replies = replies or []
        self.sent: list[tuple[str, str]] = []
        self.started: list[str | None] = []
        self.logins: list[tuple[str, str]] = []
        self.step_ups: list[tuple[str, date, str]] = []

    def start(self, customer_id: str | None) -> str:
        self.started.append(customer_id)
        return "guest"

    def login(self, customer_id: str, password: str) -> str | LoginRefused:
        self.logins.append((customer_id, password))
        return "c1" if password.endswith("-demo") else LoginRefused()

    def send(self, conversation_id: str, text: str) -> TurnResult:
        self.sent.append((conversation_id, text))
        return self.replies.pop(0) if self.replies else turn()

    def step_up(self, conversation_id: str, dob: date, last4: str) -> TurnResult:
        self.step_ups.append((conversation_id, dob, last4))
        return self.replies.pop(0) if self.replies else turn("confirmed")


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
  - id: BH-B1-03
    bullet: B1
    status: retired
    customer: SPR-1001
    turns:
      - user: "old"
    expect: {final_outcome: ANSWERED}
  - id: BH-B1-04
    bullet: B1
    customer: SPR-1001
    turns:
      - user: "submit"
      - reviewer: approve
    expect: {final_outcome: EXECUTED}
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
    assert reasons["BH-B1-03"] == "retired"  # ADR 0007 / #117: reported, never run
    assert "reviewer" in reasons["BH-B1-04"]
    assert "G-B2-01" in reasons
    assert res["not_checked"] == {"G-B1-01": ["cites_version"]}


# ---------- #103 (ADR 0007): login, guests and the step-up ----------
def test_a_customer_case_logs_in_with_the_demo_password_and_a_guest_starts(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    run(tmp_path, runner)
    assert runner.started == [None]  # G-B1-01 is a guest
    assert runner.logins == [("SPR-1001", "margaret-demo")]


def test_the_harness_answers_a_step_up_and_scores_that_turn(tmp_path: Path) -> None:
    # The golden case answers first; BH-B1-01's "yes" asks for the step-up.
    runner = FakeRunner(
        [
            turn("ok"),
            turn("quote"),
            turn("confirm it", step_up_required=True),
            turn("done", Outcome.EXECUTED),
        ]
    )
    res = run(tmp_path, runner)
    bh = next(r for r in res["records"] if r["case_id"] == "BH-B1-01")
    assert bh["verdict"] == PASS  # the final outcome is the step-up turn's: EXECUTED
    assert len(bh["trace"]) == 3
    assert runner.step_ups == [("c1", date(1958, 3, 14), LAST4)]
    assert all(DOB not in text and LAST4 not in text for _, text in runner.sent)  # never chat
    out_json, out_md = run_mod.write_results(res, tmp_path / "out")
    for p in (out_json, out_md):
        text = p.read_text()
        assert DOB not in text
        assert f'"{LAST4}"' not in text


def test_a_manual_case_scripts_its_step_ups_and_gets_no_automatic_one(tmp_path: Path) -> None:
    behavioural = """
cases:
  - id: BH-B1-09
    bullet: B1
    customer: SPR-1001
    session: {step_up: manual}
    turns:
      - user: "yes"
      - step_up: {dob: "1960-01-01", last4: "1111"}
      - step_up: correct
    expect: {final_outcome: ANSWERED}
"""
    write_golden(tmp_path, "cases: []\n", behavioural)
    runner = FakeRunner([turn("confirm it", step_up_required=True)])
    run_mod.run_suite(runner, suite="behavioural", bullet="B1", golden_dir=tmp_path)
    assert runner.step_ups == [
        ("c1", date(1960, 1, 1), "1111"),
        ("c1", date(1958, 3, 14), LAST4),
    ]


def test_a_refused_login_fails_the_case(tmp_path: Path) -> None:
    behavioural = """
cases:
  - id: BH-B1-09
    bullet: B1
    customer: SPR-9999
    turns:
      - user: "hi"
    expect: {final_outcome: ANSWERED}
"""
    write_golden(tmp_path, "cases: []\n", behavioural)
    runner = FakeRunner()
    res = run_mod.run_suite(runner, suite="behavioural", bullet="B1", golden_dir=tmp_path)
    [rec] = res["records"]
    assert (rec["verdict"], rec["failed_key"]) == (FAIL, "login")
    assert runner.sent == []


def test_leaked_value_fails_and_is_redacted(tmp_path: Path) -> None:
    res = run(tmp_path, FakeRunner([turn(f"you were born {DOB}, ok")]))
    rec = res["records"][0]
    assert (rec["verdict"], rec["failed_key"]) == (FAIL, "restricted_field")
    out_json, _ = run_mod.write_results(res, tmp_path / "out")
    assert DOB not in out_json.read_text()


def test_provider_error_in_a_step_up_is_na(tmp_path: Path) -> None:
    runner = FakeRunner(
        [
            turn("ok"),
            turn("quote"),
            turn("confirm", step_up_required=True),
            turn(provider_error=True),
        ]
    )
    res = run(tmp_path, runner)
    bh = next(r for r in res["records"] if r["case_id"] == "BH-B1-01")
    assert bh["verdict"] == NA


def test_repeat_and_scorecard(tmp_path: Path) -> None:
    res = run(tmp_path, FakeRunner(), repeat=3)
    assert len(res["records"]) == 6  # two runnable cases x 3
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
