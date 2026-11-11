"""The page smoke checks the page's imports the way Streamlit runs it (issue #166, after #161)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agents.tests.test_ui import FakeRunner
from agents.ui import smoke

ROOT = Path(__file__).parents[2]


def test_issue_166_the_smoke_fails_where_streamlit_would(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """#166, found by the post-merge review of PR #163: the smoke passed where #161 would fail."""

    class OfflineDesk:  # the page loads in-process with a fake runner, as the UI tests do
        @staticmethod
        def from_file(path: str, default_timeout: float) -> AppTest:
            at = AppTest.from_file(path, default_timeout=default_timeout)
            at.session_state["runner"] = FakeRunner()
            return at

    monkeypatch.setattr(smoke, "AppTest", OfflineDesk)
    monkeypatch.delenv("PYTHONPATH", raising=False)  # the image before #161's fix

    assert smoke.main() == 1
    assert "No module named 'agents'" in capsys.readouterr().out


def test_the_page_imports_resolve_with_the_repo_root_on_the_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(ROOT))  # as the image sets it: ENV PYTHONPATH=/app

    assert smoke.import_problems() == []
