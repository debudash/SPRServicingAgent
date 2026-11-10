"""Append-only, hash-chained audit log (FR-10, FR-25, PG-10).

Not money-path code: it records decisions, it never makes them (blueprint section 10).
"""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime

from pydantic import JsonValue

from contracts.ports import AuditEvent, AuditRecord
from contracts.tools import Node
from data.store.db import immediate

GENESIS_HASH = "0" * 64


def _row_hash(prev_hash: str, fields: dict[str, object]) -> str:
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def _hashed_fields(
    audit_id: int,
    conversation_id: str,
    case_id: str | None,
    turn: int,
    at: str,
    node: str,
    event: str,
    payload: str,
    versions: str,
) -> dict[str, object]:
    return {
        "audit_id": audit_id,
        "conversation_id": conversation_id,
        "case_id": case_id,
        "turn": turn,
        "at": at,
        "node": node,
        "event": event,
        "payload": json.loads(payload),
        "versions": json.loads(versions),
    }


_COLUMNS = (
    "audit_id, conversation_id, case_id, turn, at, node, event, payload, versions, "
    "prev_hash, row_hash"
)


def _to_record(row: tuple[object, ...]) -> AuditRecord:
    return AuditRecord(
        audit_id=row[0],
        conversation_id=row[1],
        case_id=row[2],
        turn=row[3],
        at=datetime.fromisoformat(str(row[4])),
        node=Node(str(row[5])),
        event=AuditEvent(str(row[6])),
        payload=json.loads(str(row[7])),
        versions=json.loads(str(row[8])),
        prev_hash=str(row[9]),
        row_hash=str(row[10]),
    )


class SqliteAuditLog:
    """`contracts.ports.AuditLog` on the `audit` table of `desk.db`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(
        self,
        *,
        conversation_id: str,
        turn: int,
        node: Node,
        event: AuditEvent,
        payload: dict[str, JsonValue],
        versions: dict[str, JsonValue],
        case_id: str | None = None,
    ) -> AuditRecord:
        # One immediate transaction so the read of the last hash and the insert cannot interleave.
        with immediate(self._conn):
            return self.append_in_transaction(
                conversation_id=conversation_id,
                turn=turn,
                node=node,
                event=event,
                payload=payload,
                versions=versions,
                case_id=case_id,
            )

    def append_in_transaction(
        self,
        *,
        conversation_id: str,
        turn: int,
        node: Node,
        event: AuditEvent,
        payload: dict[str, JsonValue],
        versions: dict[str, JsonValue],
        case_id: str | None = None,
    ) -> AuditRecord:
        """`append` for a caller that already holds a `BEGIN IMMEDIATE` on this connection, so the
        audit row commits or rolls back with the caller's own writes (the ledger, FR-10)."""
        if not self._conn.in_transaction:
            raise RuntimeError("append_in_transaction needs an open transaction")
        at = datetime.now(UTC).isoformat()
        payload_json = json.dumps(payload, sort_keys=True)
        versions_json = json.dumps(versions, sort_keys=True)
        last = self._conn.execute(
            "SELECT audit_id, row_hash FROM audit ORDER BY audit_id DESC LIMIT 1"
        ).fetchone()
        audit_id, prev_hash = (last[0] + 1, last[1]) if last else (1, GENESIS_HASH)
        row_hash = _row_hash(
            prev_hash,
            _hashed_fields(
                audit_id,
                conversation_id,
                case_id,
                turn,
                at,
                str(node),
                str(event),
                payload_json,
                versions_json,
            ),
        )
        self._conn.execute(
            f"INSERT INTO audit ({_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                audit_id,
                conversation_id,
                case_id,
                turn,
                at,
                str(node),
                str(event),
                payload_json,
                versions_json,
                prev_hash,
                row_hash,
            ),
        )
        return AuditRecord(
            audit_id=audit_id,
            conversation_id=conversation_id,
            case_id=case_id,
            turn=turn,
            at=datetime.fromisoformat(at),
            node=node,
            event=event,
            payload=payload,
            versions=versions,
            prev_hash=prev_hash,
            row_hash=row_hash,
        )

    def read(self, conversation_id: str) -> list[AuditRecord]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM audit WHERE conversation_id = ? ORDER BY audit_id",
            (conversation_id,),
        ).fetchall()
        return [_to_record(r) for r in rows]

    def verify_chain(self) -> bool:
        prev = GENESIS_HASH
        expected_id = 1
        for r in self._conn.execute(f"SELECT {_COLUMNS} FROM audit ORDER BY audit_id"):
            if r[0] != expected_id or r[9] != prev:
                return False
            fields = _hashed_fields(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8])
            if _row_hash(prev, fields) != r[10]:
                return False
            prev = r[10]
            expected_id += 1
        return True
