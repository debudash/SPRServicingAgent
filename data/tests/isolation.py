"""One scanner for the restricted tables (PG-04, ADR 0005, ADR 0007).

Only `data/identity.py` may name the `identity` and `logins` tables or their restricted columns.

Issue #111 (found by /code-review on PR #109): each table had its own hand-written regex, so #66's
fixes to the identity scan never reached the logins copy, and neither caught quoted or
schema-prefixed names, comma joins (logins), DDL or PRAGMA. Every restricted table now goes through
this one pattern, over every Python lane.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ALLOWED = frozenset({REPO / "data" / "identity.py"})
SCANNED_LANES = ("data", "agents", "evals", "redteam")

# Restricted table -> its restricted columns. `salt` and `dob` are common words, so columns are
# flagged only inside SQL (after a SQL keyword on the same line); the unambiguous ones always are.
RESTRICTED: dict[str, tuple[str, ...]] = {
    "identity": ("dob", "ssn_last4"),
    "logins": ("salt", "password_hash"),
}
_ALWAYS = ("ssn_last4", "password_hash")

# A table name, optionally quoted ("x", `x`, [x]) and optionally schema-prefixed (main.x).
_Q_OPEN, _Q_CLOSE = r"[\"`\[]?", r"[\"`\]]?"


def _name(table: str) -> str:
    return rf"(?:{_Q_OPEN}\w+{_Q_CLOSE}\.)?{_Q_OPEN}{table}\b{_Q_CLOSE}"


def _table_pattern(table: str) -> str:
    name = _name(table)
    return "|".join(
        [
            rf"\b(?:FROM|INTO|JOIN|UPDATE|TABLE|EXISTS)\s+{name}",  # reads, writes and DDL
            rf"\bFROM\s+[^;\n]*?,\s*{name}",  # a comma join after FROM
            rf"\bPRAGMA\s+\w+\s*\(\s*{name}",  # PRAGMA table_info(...) and friends
        ]
    )


_SQL_COLUMNS = sorted({c for cols in RESTRICTED.values() for c in cols})
FORBIDDEN = re.compile(
    "|".join(
        [_table_pattern(t) for t in RESTRICTED]
        + [rf"\b{c}\b" for c in _ALWAYS]
        + [rf"\b(?:SELECT|WHERE|SET|INSERT|UPDATE)\b[^\n#]*\b(?:{'|'.join(_SQL_COLUMNS)})\b"]
    ),
    re.IGNORECASE,
)


# A Python import ("from data.identity import ...") reads like SQL to a case-insensitive pattern.
# Importing the door is how every other module is meant to reach the tables, so those lines are
# dropped before the scan.
_PY_IMPORT = re.compile(r"^\s*from\s+[\w.]+\s+import\s.*$", re.MULTILINE)


def forbidden_sql(source: str) -> bool:
    return FORBIDDEN.search(_PY_IMPORT.sub("", source)) is not None


def violations() -> tuple[list[Path], int]:
    """Every lane module, outside tests and data/identity.py, that names a restricted table or
    column; and how many modules were scanned."""
    found: list[Path] = []
    scanned = 0
    for lane in SCANNED_LANES:
        for path in (REPO / lane).rglob("*.py"):
            if path in ALLOWED or "tests" in path.parts:
                continue
            scanned += 1
            if forbidden_sql(path.read_text(encoding="utf-8")):
                found.append(path)
    return found, scanned
