-- examples/destructive/001_create_accounts.sql
-- OUTCOME: This migration is CLEAN and would pass on its own.
-- It exists so the destroyer migration has a real table to target.

CREATE TABLE accounts (
    id       SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    balance  NUMERIC(12, 2) NOT NULL DEFAULT 0.00
);
