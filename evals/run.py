"""Run golden and behavioural cases through a `contracts.ports.LoginDeskRunner` (EVAL_SPEC 2).

    python -m evals.run --suite golden|behavioural|all --bullet B1 [--repeat 3] [--out DIR]
                        [--runner package.module:factory]

`--runner` names a zero-argument factory returning a LoginDeskRunner.

Sessions (ADR 0007, evals/golden/README.md): a customer case logs in with that customer's demo
password; `customer: null` is a guest. When a turn returns `step_up_required`, the harness answers
the step-up form with the customer's values and scores that turn (`session.step_up: auto`), unless
the case scripts its step-ups (`manual`). Restricted values (date of birth, SSN digits) are read
only to answer the step-up and to check replies; they go only to `runner.step_up`, never into a
chat message, and are redacted from everything written to the results file.
"""

from __future__ import annotations

import argparse
import importlib
import json
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from contracts.ports import LoginDeskRunner, LoginRefused, TurnResult
from evals.score import (
    FAIL,
    Restricted,
    not_checked_keys,
    render_markdown,
    score_case,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "evals" / "golden"
ACCOUNTS = ROOT / "problemstmt" / "spr_starter_kit" / "data" / "accounts.json"
DEMO_LOGINS = ROOT / "data" / "demo_logins.json"  # ADR 0007: the simulated login
RESULTS = ROOT / "evals" / "results"
BULLET_ORDER = ("B1", "B2", "B3", "B4", "B5")
CORRECT = "correct"  # a step-up answered with the customer's stored values
SUITE_FILES = {"golden": "golden.yaml", "behavioural": "behavioural.yaml"}


def load_cases(suite: str, golden_dir: Path = GOLDEN) -> list[dict[str, Any]]:
    suites = list(SUITE_FILES) if suite == "all" else [suite]
    cases: list[dict[str, Any]] = []
    for name in suites:
        for case in yaml.safe_load((golden_dir / SUITE_FILES[name]).read_text())["cases"]:
            cases.append({**case, "suite": name})
    return cases


def load_identities(path: Path = ACCOUNTS) -> dict[str, tuple[str, str]]:
    """customer_id -> (date of birth, last four). Stays inside the harness."""
    accounts = json.loads(path.read_text())["accounts"]
    return {a["customer_id"]: (a["dob"], a["last4_ssn"]) for a in accounts}


def load_passwords(path: Path = DEMO_LOGINS) -> dict[str, str]:
    """customer_id -> demo password, for logging a case in. Stays inside the harness."""
    passwords: dict[str, str] = json.loads(path.read_text())["passwords"]
    return passwords


def case_turns(case: dict[str, Any]) -> list[dict[str, Any]]:
    """The case's turns, each `{"user": text}`, `{"step_up": ...}` or `{"reviewer": ...}`."""
    if "turns" in case:
        turns: list[dict[str, Any]] = case["turns"]
        return turns
    return [{"user": case["ask"]}]


def select(
    cases: Sequence[dict[str, Any]], bullet: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Cases to run (bullets up to `bullet`, status active) and cases reported as not run."""
    started = BULLET_ORDER[: BULLET_ORDER.index(bullet) + 1]
    to_run: list[dict[str, Any]] = []
    not_run: list[dict[str, str]] = []
    for case in cases:
        if case["bullet"] not in started:
            reason = f"bullet {case['bullet']} not started"
        elif (status := case.get("status", "active")) in ("pending_data", "retired"):
            reason = status  # retired: the spec no longer describes it (#117)
        elif case.get("faults"):
            reason = "fault injection is not available through the runner yet"
        elif any("reviewer" in t for t in case_turns(case)):
            reason = "reviewer turns are not available through the runner yet"
        else:
            to_run.append(case)
            continue
        not_run.append({"case_id": case["id"], "reason": reason})
    return to_run, not_run


def _step_up_values(
    answer: Any, customer: str, identities: dict[str, tuple[str, str]]
) -> tuple[date, str]:
    """`CORRECT` is the customer's stored values; otherwise the case's own `{dob, last4}`."""
    dob, last4 = identities[customer] if answer == CORRECT else (answer["dob"], answer["last4"])
    return date.fromisoformat(str(dob)), str(last4)


def _play(
    runner: LoginDeskRunner,
    conversation: str,
    case: dict[str, Any],
    identities: dict[str, tuple[str, str]],
) -> list[TurnResult]:
    """Every turn of the case, plus each automatic step-up the desk asks for (`auto`)."""
    customer = case.get("customer")
    # Issue #120: str(None) made a guest the customer "None", so a step-up request from the desk
    # looked up identities["None"] and crashed the run. Only a logged-in customer can step up; a
    # guest's turn is scored as the desk returned it, so a desk that asks a guest fails the case.
    auto = customer is not None and (case.get("session") or {}).get("step_up", "auto") == "auto"
    turns: list[TurnResult] = []
    for step in case_turns(case):
        if "step_up" in step:
            result = runner.step_up(
                conversation, *_step_up_values(step["step_up"], str(customer), identities)
            )
        else:
            result = runner.send(conversation, str(step["user"]))
        turns.append(result)
        if not result.provider_error and auto and result.step_up_required:
            result = runner.step_up(
                conversation, *_step_up_values(CORRECT, str(customer), identities)
            )
            turns.append(result)
        if result.provider_error:
            break
    return turns


def run_case_once(
    runner: LoginDeskRunner,
    case: dict[str, Any],
    identities: dict[str, tuple[str, str]],
    restricted: Restricted,
    passwords: dict[str, str],
) -> dict[str, Any]:
    customer = case.get("customer")
    if customer is None:
        session: str | LoginRefused = runner.start(None)
    elif str(customer) not in passwords:
        raise KeyError(f"{case['id']}: no demo password for {customer} in the logins file")
    else:
        session = runner.login(str(customer), passwords[str(customer)])
    turns: list[TurnResult] = []
    key: str | None
    if isinstance(session, LoginRefused):
        score_verdict, key, detail = FAIL, "login", f"login refused for {customer}"
    else:
        turns = _play(runner, session, case, identities)
        scored = score_case(case.get("expect") or {}, turns, restricted)
        score_verdict, key, detail = scored.verdict, scored.failed_key, scored.detail
    last = turns[-1] if turns else None
    return {
        "case_id": case["id"],
        "suite": case["suite"],
        "bullet": case["bullet"],
        "verdict": score_verdict,
        "failed_key": key,
        "detail": detail,
        "outcome": last.outcome.value if last else None,
        "trace": [
            {
                "turn": t.turn,
                "reply": t.reply_text,
                "outcome": t.outcome.value,
                "steps": [s.value for s in t.steps],
                "nodes": [n.value for n in t.nodes],
                "citations": [c.model_dump(mode="json") for c in t.citations],
            }
            for t in turns
        ],
        "usage": [t.usage.model_dump(mode="json") for t in turns],
        "latency_ms": [t.latency_ms for t in turns],
    }


def run_suite(
    runner: LoginDeskRunner,
    *,
    suite: str,
    bullet: str,
    repeat: int = 1,
    golden_dir: Path = GOLDEN,
    accounts: Path = ACCOUNTS,
    logins: Path = DEMO_LOGINS,
    run_id: str | None = None,
) -> dict[str, Any]:
    identities = load_identities(accounts)
    passwords = load_passwords(logins)
    restricted = Restricted(
        frozenset(d for d, _ in identities.values()), frozenset(s for _, s in identities.values())
    )
    to_run, not_run = select(load_cases(suite, golden_dir), bullet)
    records: list[dict[str, Any]] = []
    for case in to_run:
        for n in range(1, repeat + 1):
            rec = run_case_once(runner, case, identities, restricted, passwords)
            records.append({**rec, "repeat": n})
    results = {
        "run_id": run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "suite": suite,
        "bullets": list(BULLET_ORDER[: BULLET_ORDER.index(bullet) + 1]),
        "repeat": repeat,
        "records": records,
        "not_run": not_run,
        "not_checked": {
            c["id"]: list(keys) for c in to_run if (keys := not_checked_keys(c.get("expect") or {}))
        },
    }
    redacted: dict[str, Any] = restricted.redact_json(results)
    return redacted


def write_results(results: dict[str, Any], out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{results['run_id']}.json"
    md_path = out / f"{results['run_id']}.md"
    json_path.write_text(json.dumps(results, indent=2) + "\n")
    md_path.write_text(render_markdown(results))
    return json_path, md_path


def _load_runner(spec: str) -> LoginDeskRunner:
    module, _, attr = spec.partition(":")
    runner: LoginDeskRunner = getattr(importlib.import_module(module), attr)()
    return runner


def main(argv: Sequence[str] | None = None, runner: LoginDeskRunner | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run")
    parser.add_argument("--suite", choices=["golden", "behavioural", "all"], default="all")
    parser.add_argument("--bullet", choices=BULLET_ORDER, default="B1")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--out", type=Path, default=RESULTS)
    parser.add_argument("--runner", help="module:factory returning a LoginDeskRunner")
    args = parser.parse_args(argv)
    if runner is None:
        if not args.runner:
            parser.error("no runner: pass --runner module:factory returning a LoginDeskRunner")
        runner = _load_runner(args.runner)
    results = run_suite(runner, suite=args.suite, bullet=args.bullet, repeat=args.repeat)
    json_path, md_path = write_results(results, args.out)
    print(f"wrote {json_path} and {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
