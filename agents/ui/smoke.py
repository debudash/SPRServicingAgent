"""Page smoke test: load the desk's pages the way Streamlit runs them in the container, and fail on
any exception (issue #161: the page failed with "No module named 'agents'" while every other check
passed, because tests import from the repo root and Streamlit puts only agents/ui on the path).

Run inside the desk container from outside the repo root:
    docker compose exec -T desk sh -c "cd / && python -m agents.ui.smoke"
`python -m` needs /app on the path, which is exactly what the image must provide (PYTHONPATH).
No model is called: it opens the login page, the review queue and the behaviour demo, and runs one
offline demo scenario.
"""

import subprocess
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).with_name("app.py"))
PROBE = str(Path(__file__).with_name("import_probe.py"))


def import_problems() -> list[str]:
    """Issue #166: AppTest loads app.py inside this process, where `agents` is already imported, so
    the page checks below passed even with #161's broken path. The probe runs as a script from
    agents/ui in a fresh interpreter with this environment, the way Streamlit loads the page, so
    a page import that only resolves from the repo root fails here."""
    run = subprocess.run([sys.executable, PROBE], capture_output=True, text=True, check=False)
    out = (run.stdout + run.stderr).strip()
    if run.returncode == 0:
        print(out)
        return []
    return [out or f"import probe exited {run.returncode}"]


def main() -> int:
    problems = import_problems()
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()

    def check(where: str) -> None:
        if at.exception:
            problems.append(f"{where}: {at.exception[0].value}")

    check("login page")
    if not at.selectbox(key="login_customer").options:
        problems.append("login page: no customers in the dropdown")
    if [b for b in at.button if b.key == "open_review"]:
        at.button(key="open_review").click().run()
        check("review queue")
        at.button(key="close_review").click().run()
    if [b for b in at.button if b.key == "open_demo"]:
        at.button(key="open_demo").click().run()
        check("behaviour demo")
        at.button(key="demo_run").click().run()
        check("behaviour demo, one scenario run")
    for p in problems:
        print("FAIL", p)
    print("page smoke:", "FAIL" if problems else "PASS")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
