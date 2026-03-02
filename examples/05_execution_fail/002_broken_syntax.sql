-- ============================================================
-- SCENARIO 5: EXECUTION FAILURE (SQL SYNTAX ERROR)
-- 002_broken_syntax.sql
--
-- This migration passes safety analysis (no destructive patterns)
-- and passes the ordering check (version 002 is correct).
-- It fails at EXECUTION TIME when PostgreSQL tries to parse it.
--
-- The syntax error is embedded on line 12 below.
-- This simulates a copy-paste mistake, a bad find-and-replace,
-- or a migration that was edited after being committed.
--
-- PostgreSQL rolls back this migration entirely (DDL is transactional).
-- The accounts table from 001 is also rolled back if it was in the
-- same transaction. Migration 003 never runs.
--
-- SafeDB-CI reports:
--   MIGRATION FAILED:
--   Postgres migration failed (v2 - 002_broken_syntax.sql):
--   syntax error at or near "GIBBERISH"
-- ============================================================

CREATE TABLE transactions (
    id         SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    amount     NUMERIC(12, 2) NOT NULL,

    -- SYNTAX ERROR: The line below is intentionally corrupt.
    -- This is not valid SQL. PostgreSQL will reject the entire statement.
    GIBBERISH THIS IS NOT VALID SQL AT ALL CRASH HERE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
