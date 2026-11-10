-- B3 (issue #87): proposals and approvals (ARCHITECTURE section 2.2). Money is integer cents.
-- `transactions` already exists (0002) with proposal_id UNIQUE, the FR-09 idempotency key. SQLite
-- cannot add a foreign key to an existing table, so its link to `proposals` is enforced by the
-- ledger, the table's only writer.

CREATE TABLE proposals (
    proposal_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    customer_id TEXT NOT NULL REFERENCES accounts (customer_id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    free_cents INTEGER NOT NULL CHECK (free_cents >= 0),
    excess_cents INTEGER NOT NULL CHECK (excess_cents >= 0),
    rate_bp INTEGER NOT NULL CHECK (rate_bp BETWEEN 0 AND 10000),
    charge_cents INTEGER NOT NULL CHECK (charge_cents >= 0),
    net_cents INTEGER NOT NULL CHECK (net_cents >= 0),
    contract_year INTEGER NOT NULL CHECK (contract_year >= 1),
    threshold_tier TEXT NOT NULL CHECK (threshold_tier IN ('self_service', 'human')),
    irs_notice INTEGER NOT NULL CHECK (irs_notice IN (0, 1)),
    as_of TEXT NOT NULL,
    hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'quoted'
        CHECK (status IN ('quoted', 'confirmed', 'approved', 'executed', 'voided', 'escalated')),
    quoted_turn INTEGER NOT NULL CHECK (quoted_turn >= 1),
    confirmed_turn INTEGER CHECK (confirmed_turn > quoted_turn),
    created_at TEXT NOT NULL
);

CREATE INDEX proposals_conversation ON proposals (conversation_id);

CREATE TABLE approvals (
    approval_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL REFERENCES proposals (proposal_id),
    approver TEXT NOT NULL,
    decision TEXT NOT NULL
        CHECK (decision IN ('approve', 'hold', 'escalate', 'reject', 'request_info')),
    -- Compliance's cited reasons travel in its `compliance_decided` audit row; the Approval
    -- message carries none yet, so this stays an empty list until a contract adds them.
    reasons TEXT NOT NULL DEFAULT '[]',
    token_hmac TEXT CHECK ((decision = 'approve') = (token_hmac IS NOT NULL)),
    used_at_turn INTEGER,
    recorded_at TEXT NOT NULL
);

CREATE INDEX approvals_proposal ON approvals (proposal_id);
