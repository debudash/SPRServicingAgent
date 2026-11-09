"""Issue #36: desk store and append-only audit log."""

import sqlite3
from pathlib import Path

import pytest

from contracts.ports import AuditEvent, AuditLog
from contracts.tools import Node
from data.store.audit import GENESIS_HASH, SqliteAuditLog
from data.store.db import MIGRATIONS_DIR, open_db


def _log(tmp_path: Path) -> tuple[sqlite3.Connection, SqliteAuditLog]:
    conn = open_db(tmp_path / "desk.db")
    return conn, SqliteAuditLog(conn)


def _append(log: AuditLog, conv: str = "c1", turn: int = 1) -> None:
    log.append(
        conversation_id=conv,
        turn=turn,
        node=Node.INTAKE,
        event=next(iter(AuditEvent)),
        payload={"k": [1, "x"]},
        versions={"contracts": "1"},
    )


def test_port_assignment(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "desk.db")
    log: AuditLog = SqliteAuditLog(conn)
    assert log.verify_chain()


def test_round_trip_in_order(tmp_path: Path) -> None:
    _, log = _log(tmp_path)
    a = log.append(
        conversation_id="c1",
        turn=1,
        node=Node.CASE,
        event=next(iter(AuditEvent)),
        payload={"a": 1},
        versions={},
        case_id="K1",
    )
    _append(log, "c2")
    _append(log, "c1", turn=2)
    rows = log.read("c1")
    assert [r.turn for r in rows] == [1, 2]
    assert rows[0] == a
    assert a.prev_hash == GENESIS_HASH
    assert rows[1].prev_hash != a.row_hash  # chain is global: c2 sits between
    assert a.at.utcoffset() is not None and a.at.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
    assert log.verify_chain()


def test_update_and_delete_rejected(tmp_path: Path) -> None:
    conn, log = _log(tmp_path)
    _append(log)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE audit SET turn = 9")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM audit")
    assert log.verify_chain()


def test_edit_detected_when_triggers_dropped(tmp_path: Path) -> None:
    conn, log = _log(tmp_path)
    _append(log)
    _append(log, turn=2)
    conn.execute("DROP TRIGGER audit_no_update")
    conn.execute("DROP TRIGGER audit_no_delete")
    conn.execute("UPDATE audit SET payload = '{\"k\": 2}' WHERE audit_id = 1")
    assert not log.verify_chain()


def test_delete_detected_when_triggers_dropped(tmp_path: Path) -> None:
    conn, log = _log(tmp_path)
    for t in (1, 2, 3):
        _append(log, turn=t)
    conn.execute("DROP TRIGGER audit_no_delete")
    conn.execute("DELETE FROM audit WHERE audit_id = 2")
    assert not log.verify_chain()


def test_migrations_apply_once(tmp_path: Path) -> None:
    path = tmp_path / "desk.db"
    open_db(path).close()
    conn = open_db(path)
    # Every migration file exactly once, in order, after two opens (was `== [(1,)]` before
    # migration 0002 existed, issue #57).
    expected = sorted(int(f.name.split("_")[0]) for f in MIGRATIONS_DIR.glob("*.sql"))
    assert len(expected) >= 2
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    assert [r[0] for r in rows] == expected
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"conversations", "audit"} <= names
