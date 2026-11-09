"""The night-shift publish job rejects agent PRs that touch integrator paths. This test reads the
regex from the workflow itself, so a typo there cannot silently let an agent edit the answer key."""

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "night-shift-lane.yml"


def _protected_regex() -> re.Pattern[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"grep -qE '([^']+)'", text)
    assert match, "protected-path grep not found in night-shift-lane.yml"
    return re.compile(match.group(1))


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        "CLAUDE.md",
        "contracts/state.py",
        "evals/golden/golden.yaml",
        "baseline/agent/tools.py",
        "knowledge/fee_schedule.md",
        "agents/.claude/settings.json",
    ],
)
def test_integrator_paths_are_protected(path: str) -> None:
    assert _protected_regex().search(path)


@pytest.mark.parametrize(
    "path",
    [
        "data/quote/calculator.py",
        "agents/graph.py",
        "evals/run.py",
        "redteam/attacks.yaml",
        "progress/data/2026-11-09-issue-4.md",
        "docs/knowledge-notes.md",
    ],
)
def test_lane_paths_are_not_protected(path: str) -> None:
    assert not _protected_regex().search(path)
