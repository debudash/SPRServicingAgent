"""The page smoke (agents/ui/smoke.py) fails on what it cannot check, not only on exceptions."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agents.tests.test_ui import FakeRunner
from agents.ui import smoke

APP = str(Path(__file__).parents[1] / "ui" / "app.py")


def test_issue_165_a_missing_review_queue_fails_the_smoke(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """#165, found by the post-merge review of PR #163: a missing page was skipped, still PASS."""

    class NoReviewDesk:
        @staticmethod
        def from_file(path: str, default_timeout: float) -> AppTest:
            at = AppTest.from_file(APP, default_timeout=default_timeout)
            at.session_state["runner"] = FakeRunner()  # and no "review": the queue button is hidden
            return at

    monkeypatch.setattr(smoke, "AppTest", NoReviewDesk)

    assert smoke.main() == 1
    out = capsys.readouterr().out
    assert "FAIL review queue" in out
    assert "page smoke: FAIL" in out
