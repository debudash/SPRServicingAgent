"""Page smoke test: load the desk's pages the way Streamlit runs them in the container, and fail on
any exception (issue #161: the page failed with "No module named 'agents'" while every other check
passed, because tests import from the repo root and Streamlit puts only agents/ui on the path).

Run inside the desk container from outside the repo root:
    docker compose exec -T desk sh -c "cd / && python -m agents.ui.smoke"
`python -m` needs /app on the path, which is exactly what the image must provide (PYTHONPATH).
No model is called: it opens the login page, the review queue and the behaviour demo, and runs one
offline demo scenario.
"""

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).with_name("app.py"))


def main() -> int:
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    problems: list[str] = []

    def check(where: str) -> None:
        if at.exception:
            problems.append(f"{where}: {at.exception[0].value}")

    # Issue #165: a missing button used to skip its page and still print PASS (found when the review
    # desk was absent: no queue button, nothing checked). Every page is expected in the container,
    # so a button that is not there is a failure, reported under the page it should have opened.
    def click(key: str, where: str) -> bool:
        if not [b for b in at.button if b.key == key]:
            problems.append(f"{where}: no {key!r} button")
            return False
        at.button(key=key).click().run()
        return True

    check("login page")
    if not at.selectbox(key="login_customer").options:
        problems.append("login page: no customers in the dropdown")
    if click("open_review", "review queue"):
        check("review queue")
        click("close_review", "review queue")
    if click("open_demo", "behaviour demo"):
        check("behaviour demo")
        if click("demo_run", "behaviour demo, one scenario run"):
            check("behaviour demo, one scenario run")
    for p in problems:
        print("FAIL", p)
    print("page smoke:", "FAIL" if problems else "PASS")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
