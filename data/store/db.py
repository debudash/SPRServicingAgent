"""Open `desk.db` and apply numbered SQL migrations once each (ARCHITECTURE.md section 2.2)."""

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME = re.compile(r"^(\d+)_.*\.sql$")


def _migration_files(directory: Path) -> list[tuple[int, Path]]:
    found = [(int(m.group(1)), p) for p in directory.glob("*.sql") if (m := _NAME.match(p.name))]
    return sorted(found)


def migrate(conn: sqlite3.Connection, directory: Path = MIGRATIONS_DIR) -> None:
    """Apply each numbered migration not yet recorded in `schema_migrations`."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    for version, path in _migration_files(directory):
        if version in applied:
            continue
        # executescript commits; the version row is written right after, and each file is
        # small, so a crash between the two is an operator re-run of a fresh database.
        conn.executescript(path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) "
            "VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
            (version, path.name),
        )
        conn.commit()


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the desk database at `path` and migrate it to the latest schema."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


@contextmanager
def immediate(conn: sqlite3.Connection) -> Iterator[None]:
    """One write transaction: `BEGIN IMMEDIATE`, then COMMIT, or ROLLBACK on any exception
    (an interrupt included, as in audit.py). Reads inside it see a state no other writer can change
    before the commit. Not reentrant: SQLite has no nested BEGIN."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
