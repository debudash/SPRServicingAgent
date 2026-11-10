"""Scorer for eval cases (docs/EVAL_SPEC.md sections 2-3, evals/golden/README.md "Expectations").

`score_case` grades one run of one case from the `TurnResult`s it produced. Only the keys that
`TurnResult` can answer today are checked; the rest are listed as "not checked yet" so a pass never
claims more than was measured. `python -m evals.score <results.json>` writes the markdown scorecard.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from contracts.ports import TurnResult
from evals.claims import find_claims

PASS = "pass"
FAIL = "fail"
NA = "na"

RESTRICTED_FIELD = "restricted_field"  # the every-case GR-09 check, not a case key

# Keys TurnResult cannot answer yet (they need the transactions table or the case packet).
# `forbid_claims` is checked through evals.claims; `cites_version` against knowledge/ (#123).
NOT_CHECKED_KEYS = ("executed", "executions", "case_packet_fields")
KNOWLEDGE = Path(__file__).resolve().parents[1] / "knowledge"
AS_OF = date(2024, 12, 1)  # PRD D-04: the date every case is answered as of
CHECKED_KEYS = (
    "outcome",
    "final_outcome",
    "contains",
    "not_contains",
    "numbers",
    "cites",
    "cites_any",
    "cites_version",
    "tools",
    "not_tools",
    "order",
    "forbid_claims",
)


@dataclass(frozen=True)
class Restricted:
    """Restricted values (GR-09). They live only in the harness; never written to results."""

    dobs: frozenset[str] = frozenset()
    last4s: frozenset[str] = frozenset()

    def _last4_re(self) -> re.Pattern[str] | None:
        if not self.last4s:
            return None
        return re.compile(r"(?<![\d,.])(?:" + "|".join(map(re.escape, self.last4s)) + r")(?!\d)")

    def found_in(self, text: str) -> bool:
        if any(d in text for d in self.dobs):
            return True
        pattern = self._last4_re()
        return bool(pattern and pattern.search(text))

    def redact(self, text: str) -> str:
        for d in self.dobs:
            text = text.replace(d, "[REDACTED]")
        pattern = self._last4_re()
        return pattern.sub("[REDACTED]", text) if pattern else text

    def redact_json(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, list):
            return [self.redact_json(v) for v in value]
        if isinstance(value, dict):
            return {k: self.redact_json(v) for k, v in value.items()}
        return value


@dataclass(frozen=True)
class CaseScore:
    verdict: str  # pass | fail | na
    failed_key: str | None = None
    detail: str = ""
    not_checked: tuple[str, ...] = field(default=())


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def _squash(text: str) -> str:
    return text.replace("$", "").replace(" ", "")


def _is_subsequence(wanted: Sequence[str], seen: Sequence[str]) -> bool:
    it = iter(seen)
    return all(any(step == w for step in it) for w in wanted)


@cache
def versions_in_force(knowledge: Path = KNOWLEDGE, as_of: date = AS_OF) -> dict[str, int]:
    """doc_id -> the version in force at `as_of`: the highest version effective on or before it.
    Read from the documents' front matter (knowledge/README.md), the same rule retrieval uses."""
    in_force: dict[str, int] = {}
    for path in sorted(knowledge.glob("*.md")):
        if path.name == "README.md":
            continue
        meta = yaml.safe_load(path.read_text(encoding="utf-8").split("---\n", 2)[1])
        effective = meta["effective_date"]
        if date.fromisoformat(str(effective)) <= as_of:
            doc_id, version = str(meta["doc_id"]), int(meta["version"])
            in_force[doc_id] = max(in_force.get(doc_id, 0), version)
    return in_force


def not_checked_keys(expect: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(k for k in expect if k not in CHECKED_KEYS)


def score_case(
    expect: Mapping[str, Any],
    turns: Sequence[TurnResult],
    restricted: Restricted | None = None,
    in_force: Mapping[str, int] | None = None,
) -> CaseScore:
    """Grade the scored turns of one run. Reports the first failing key, in README order.

    `in_force` (doc_id -> version) defaults to `versions_in_force()` over knowledge/.
    """
    skipped = not_checked_keys(expect)
    if any(t.provider_error for t in turns) or not turns:
        return CaseScore(NA, detail="provider error", not_checked=skipped)

    def fail(key: str, detail: str) -> CaseScore:
        return CaseScore(FAIL, key, detail, skipped)

    answer = "\n".join(t.reply_text for t in turns)
    answer_lc = answer.lower()
    squashed = _squash(answer)
    steps = [s.value for t in turns for s in t.steps]
    citations = [c for t in turns for c in t.citations]
    cited_ids = {c.doc_id for c in citations}

    if restricted is not None and restricted.found_in(answer):
        return fail(RESTRICTED_FIELD, "a date of birth or SSN digits appeared in a reply")

    want = expect.get("outcome", expect.get("final_outcome"))
    if want is not None:
        key = "outcome" if "outcome" in expect else "final_outcome"
        if turns[-1].outcome.value != str(want):
            return fail(key, f"expected {want}, got {turns[-1].outcome.value}")
    for s in _as_list(expect.get("contains")):
        if s.lower() not in answer_lc:
            return fail("contains", f"missing {s!r}")
    for s in _as_list(expect.get("not_contains")):
        if s.lower() in answer_lc:
            return fail("not_contains", f"found {s!r}")
    for n in _as_list(expect.get("numbers")):
        if _squash(n) not in squashed:
            return fail("numbers", f"missing {n!r}")
    cites = _as_list(expect.get("cites"))
    if cites and not set(cites) <= cited_ids:
        return fail("cites", f"missing {sorted(set(cites) - cited_ids)}")
    cites_any = _as_list(expect.get("cites_any"))
    if cites_any and not set(cites_any) & cited_ids:
        return fail("cites_any", f"none of {cites_any} cited")
    if expect.get("cites_version") == "current":
        current = versions_in_force() if in_force is None else in_force
        stale = sorted(
            f"{c.doc_id} v{c.version}" for c in citations if current.get(c.doc_id) != c.version
        )
        if stale:
            return fail("cites_version", f"not the version in force: {stale}")
    for t in _as_list(expect.get("tools")):
        if t not in steps:
            return fail("tools", f"{t} not called")
    for t in _as_list(expect.get("not_tools")):
        if t in steps:
            return fail("not_tools", f"{t} was called")
    order = _as_list(expect.get("order"))
    if order and not _is_subsequence(order, steps):
        return fail("order", f"expected {order} in order, saw {steps}")
    forbidden = set(_as_list(expect.get("forbid_claims")))
    if forbidden:
        hit = forbidden & find_claims(answer)
        if hit:
            return fail("forbid_claims", f"claims found: {sorted(hit)}")
    return CaseScore(PASS, not_checked=skipped)


# ---------- aggregation and the scorecard ----------
def case_status(verdicts: Sequence[str]) -> str:
    """pass^k over the repeats: pass only if every non-na repeat passes; flaky if they disagree."""
    real = [v for v in verdicts if v != NA]
    if not real:
        return NA
    if all(v == PASS for v in real):
        return PASS
    return "flaky" if PASS in real else FAIL


def summarize(results: Mapping[str, Any]) -> dict[str, Any]:
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in results["records"]:
        by_case[rec["case_id"]].append(rec)
    statuses = {cid: case_status([r["verdict"] for r in recs]) for cid, recs in by_case.items()}
    counts = {k: sum(1 for s in statuses.values() if s == k) for k in (PASS, FAIL, "flaky", NA)}
    graded = counts[PASS] + counts[FAIL] + counts["flaky"]
    na_runs = sum(1 for r in results["records"] if r["verdict"] == NA)
    return {
        "statuses": statuses,
        "counts": counts,
        "pass_rate": (counts[PASS] / graded) if graded else None,
        "na_runs": na_runs,
        "total_runs": len(results["records"]),
    }


def render_markdown(results: Mapping[str, Any]) -> str:
    s = summarize(results)
    c = s["counts"]
    rate = "n/a" if s["pass_rate"] is None else f"{s['pass_rate']:.0%}"
    out = [
        f"# Eval scorecard {results['run_id']}",
        "",
        f"Suite `{results['suite']}`, bullets {', '.join(results['bullets'])}, "
        f"repeat {results['repeat']}.",
        "",
        "| Pass^k rate | Pass | Fail | Flaky | na cases | na runs |",
        "|---|---|---|---|---|---|",
        f"| {rate} | {c[PASS]} | {c[FAIL]} | {c['flaky']} | {c[NA]} | "
        f"{s['na_runs']} of {s['total_runs']} |",
        "",
    ]
    if s["total_runs"] and s["na_runs"] / s["total_runs"] > 0.10:
        out += ["**More than 10% of runs were `na`: re-run, do not report this scorecard.**", ""]
    out += ["## Cases", "", "| Case | Status | First failing key | Detail |", "|---|---|---|---|"]
    first_fail: dict[str, dict[str, Any]] = {}
    for rec in results["records"]:
        if rec["verdict"] == FAIL:
            first_fail.setdefault(rec["case_id"], rec)
    for cid, status in s["statuses"].items():
        f = first_fail.get(cid, {})
        out.append(f"| {cid} | {status} | {f.get('failed_key') or ''} | {f.get('detail') or ''} |")
    if results["not_run"]:
        out += ["", "## Not yet run", "", "| Case | Reason |", "|---|---|"]
        out += [f"| {n['case_id']} | {n['reason']} |" for n in results["not_run"]]
    if results["not_checked"]:
        out += ["", "## Not checked yet", "", "| Case | Keys |", "|---|---|"]
        out += [f"| {cid} | {', '.join(keys)} |" for cid, keys in results["not_checked"].items()]
    return "\n".join(out) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m evals.score evals/results/<run_id>.json", file=sys.stderr)
        return 2
    path = Path(args[0])
    results = json.loads(path.read_text())
    path.with_suffix(".md").write_text(render_markdown(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
