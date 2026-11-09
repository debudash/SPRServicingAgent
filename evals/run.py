"""Run golden and behavioural cases through any `contracts.ports.DeskRunner` (EVAL_SPEC section 2).

    python -m evals.run --suite golden|behavioural|all --bullet B1 [--repeat 3] [--out DIR]
                        [--runner package.module:factory]

The real runner is wired later; `--runner` names a zero-argument factory returning a DeskRunner.
Restricted values (date of birth, SSN digits) are read only to run the unscored verification turn
and to check replies; they are redacted from everything written to the results file.
"""

from __future__ import annotations

import argparse
import importlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from contracts.ports import DeskRunner, TurnResult
from evals.score import (
    NA,
    Restricted,
    not_checked_keys,
    render_markdown,
    score_case,
)

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "evals" / "golden"
ACCOUNTS = ROOT / "problemstmt" / "spr_starter_kit" / "data" / "accounts.json"
RESULTS = ROOT / "evals" / "results"
BULLET_ORDER = ("B1", "B2", "B3", "B4", "B5")
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


def case_turns(case: dict[str, Any]) -> list[str]:
    if "turns" in case:
        return [t["user"] for t in case["turns"]]
    return [case["ask"]]


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
        elif case.get("status", "active") == "pending_data":
            reason = "pending_data"
        elif case.get("faults"):
            reason = "fault injection is not available through DeskRunner yet"
        else:
            to_run.append(case)
            continue
        not_run.append({"case_id": case["id"], "reason": reason})
    return to_run, not_run


def run_case_once(
    runner: DeskRunner,
    case: dict[str, Any],
    identities: dict[str, tuple[str, str]],
    restricted: Restricted,
) -> dict[str, Any]:
    customer = case.get("customer")
    conversation = runner.start(customer)
    setup_error = False
    if (case.get("session") or {}).get("gate_b_passed"):
        dob, last4 = identities[str(customer)]
        verify = runner.send(
            conversation, f"My date of birth is {dob} and the last four of my SSN are {last4}."
        )
        setup_error = verify.provider_error  # run, not scored
    turns: list[TurnResult] = []
    if not setup_error:
        for text in case_turns(case):
            result = runner.send(conversation, text)
            turns.append(result)
            if result.provider_error:
                break
    if setup_error:
        score_verdict, key, detail = NA, None, "provider error"
    else:
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
    runner: DeskRunner,
    *,
    suite: str,
    bullet: str,
    repeat: int = 1,
    golden_dir: Path = GOLDEN,
    accounts: Path = ACCOUNTS,
    run_id: str | None = None,
) -> dict[str, Any]:
    identities = load_identities(accounts)
    restricted = Restricted(
        frozenset(d for d, _ in identities.values()), frozenset(s for _, s in identities.values())
    )
    to_run, not_run = select(load_cases(suite, golden_dir), bullet)
    records: list[dict[str, Any]] = []
    for case in to_run:
        for n in range(1, repeat + 1):
            rec = run_case_once(runner, case, identities, restricted)
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


def _load_runner(spec: str) -> DeskRunner:
    module, _, attr = spec.partition(":")
    runner: DeskRunner = getattr(importlib.import_module(module), attr)()
    return runner


def main(argv: Sequence[str] | None = None, runner: DeskRunner | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.run")
    parser.add_argument("--suite", choices=["golden", "behavioural", "all"], default="all")
    parser.add_argument("--bullet", choices=BULLET_ORDER, default="B1")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--out", type=Path, default=RESULTS)
    parser.add_argument("--runner", help="module:factory returning a DeskRunner")
    args = parser.parse_args(argv)
    if runner is None:
        if not args.runner:
            parser.error(
                "no DeskRunner: pass --runner module:factory (the real one is wired later)"
            )
        runner = _load_runner(args.runner)
    results = run_suite(runner, suite=args.suite, bullet=args.bullet, repeat=args.repeat)
    json_path, md_path = write_results(results, args.out)
    print(f"wrote {json_path} and {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
