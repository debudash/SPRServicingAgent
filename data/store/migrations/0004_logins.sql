-- ADR 0007 (issue #101): the simulated upstream login. Read and written only by data/identity.py
-- (PG-04). A salted scrypt hash, never the password; the parameters are stored per row so they
-- can be raised later without invalidating existing rows.

CREATE TABLE logins (
    customer_id TEXT PRIMARY KEY REFERENCES accounts (customer_id),
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    scrypt_n INTEGER NOT NULL,
    scrypt_r INTEGER NOT NULL,
    scrypt_p INTEGER NOT NULL
);
