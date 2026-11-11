"""`python -m agents.demo`: run the nine behaviour-demo scenarios offline and print a table.

`--verbose` prints every turn, ledger row and audit event. Exits non-zero if any scenario fails.
"""

import argparse
import io
import sys

from agents.demo.scenarios import ScenarioRun, as_text, run_all


def table(runs: list[ScenarioRun]) -> str:
    rows = [("#", "Scenario", "Outcome", "Executed", "Result", "ms")]
    rows += [
        (
            str(r.scenario.number),
            r.scenario.title,
            r.outcome,
            str(r.executions),
            "PASS" if r.passed else "FAIL",
            str(r.elapsed_ms),
        )
        for r in runs
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return "\n".join(
        "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)) for row in rows
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="print every turn and audit row")
    args = parser.parse_args(argv)
    if isinstance(sys.stdout, io.TextIOWrapper):  # a console that cannot print "§" still runs
        sys.stdout.reconfigure(errors="replace")
    runs = run_all()
    if args.verbose:
        for r in runs:
            print(as_text(r), end="\n\n")
    print(table(runs))
    failed = [r for r in runs if not r.passed]
    for r in failed:
        print(f"\nScenario {r.scenario.number} failed: " + "; ".join(r.failures))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
