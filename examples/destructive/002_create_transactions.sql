-- examples/destructive/002_create_transactions.sql
-- OUTCOME: CLEAN — creates a transactions table referencing accounts.

CREATE TABLE transactions (
    id         SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    amount     NUMERIC(12, 2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
