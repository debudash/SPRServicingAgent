"""Import every module app.py imports, on the path Streamlit gives the page (issue #166).

Run as a script, never with -m: `python agents/ui/import_probe.py`. Then sys.path[0] is agents/ui
and nothing else of the repo is on the path unless PYTHONPATH puts it there, which is exactly how
`streamlit run` loads app.py. Prints one PASS or FAIL line; exits 1 on the first import that fails.
"""

import ast
import importlib
import sys
from pathlib import Path

APP = Path(__file__).with_name("app.py")


def app_imports() -> list[str]:
    """The absolute modules app.py imports at the top level, read from its source."""
    names: list[str] = []
    for node in ast.parse(APP.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def main() -> int:
    names = app_imports()
    for name in names:
        try:
            importlib.import_module(name)
        except ImportError as e:
            print(f"page imports: FAIL {name}: {e}")
            return 1
    print(f"page imports: PASS ({len(names)} modules)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
