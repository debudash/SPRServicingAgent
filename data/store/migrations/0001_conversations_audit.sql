CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY,
    customer_id TEXT,
    started_at TEXT NOT NULL,
    as_of TEXT NOT NULL,
    gate_b_passed INTEGER NOT NULL DEFAULT 0,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked INTEGER NOT NULL DEFAULT 0,
    cost_usd_micros INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    case_id TEXT,
    turn INTEGER NOT NULL,
    at TEXT NOT NULL,
    node TEXT NOT NULL,
    event TEXT NOT NULL,
    payload TEXT NOT NULL,
    versions TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    row_hash TEXT NOT NULL
);

CREATE INDEX audit_conversation ON audit (conversation_id, audit_id);

CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit
BEGIN
    SELECT RAISE(ABORT, 'audit rows are append-only');
END;

CREATE TRIGGER audit_no_delete BEFORE DELETE ON audit
BEGIN
    SELECT RAISE(ABORT, 'audit rows are append-only');
END;
