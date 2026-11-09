-- B2 (issue #57): accounts, the identity split, beneficiaries, transactions and cases.
-- Money is integer cents (ARCHITECTURE section 2.2). Restricted columns live only in `identity`.

CREATE TABLE accounts (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    account_status TEXT NOT NULL CHECK (account_status IN ('active', 'frozen', 'deceased')),
    gate_a_trusted INTEGER NOT NULL CHECK (gate_a_trusted IN (0, 1)),
    balance_cents INTEGER NOT NULL CHECK (balance_cents >= 0),
    initial_deposit_cents INTEGER NOT NULL CHECK (initial_deposit_cents >= 0),
    contract_start_date TEXT NOT NULL,
    contract_year_stored INTEGER,
    is_synthetic INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0, 1))
);

-- Read and written only by data/identity.py (PG-04).
CREATE TABLE identity (
    customer_id TEXT PRIMARY KEY REFERENCES accounts (customer_id),
    dob TEXT NOT NULL,
    ssn_last4 TEXT NOT NULL CHECK (length(ssn_last4) = 4)
);

CREATE TABLE beneficiaries (
    beneficiary_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL REFERENCES accounts (customer_id),
    name TEXT NOT NULL,
    relationship TEXT NOT NULL,
    percentage INTEGER NOT NULL CHECK (percentage BETWEEN 0 AND 100)
);

-- Written by `execute` only (B3). proposal_id is the idempotency key (FR-09); the proposals
-- table and its foreign key arrive with B3.
CREATE TABLE transactions (
    transaction_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES accounts (customer_id),
    proposal_id TEXT UNIQUE,
    contract_year INTEGER NOT NULL CHECK (contract_year >= 1),
    gross_cents INTEGER NOT NULL CHECK (gross_cents > 0),
    free_cents INTEGER NOT NULL CHECK (free_cents >= 0),
    excess_cents INTEGER NOT NULL CHECK (excess_cents >= 0),
    charge_cents INTEGER NOT NULL CHECK (charge_cents >= 0),
    net_cents INTEGER NOT NULL CHECK (net_cents >= 0),
    approved_by TEXT NOT NULL,
    executed_as_of TEXT NOT NULL,
    is_synthetic INTEGER NOT NULL DEFAULT 0 CHECK (is_synthetic IN (0, 1))
);

CREATE INDEX transactions_customer_year ON transactions (customer_id, contract_year);

CREATE TABLE cases (
    case_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    customer_id TEXT REFERENCES accounts (customer_id),
    proposal_id TEXT,
    opened_for TEXT NOT NULL,
    reasons TEXT NOT NULL,
    packet TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'info_requested', 'approved', 'rejected', 'closed')),
    opened_at TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT
);
