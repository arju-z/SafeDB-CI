-- ============================================================
-- SCENARIO 5: EXECUTION FAILURE (SQL SYNTAX ERROR)
-- Expected outcome: PHASE 3 FAILS — exit 1
--
-- Safety check passes (no destructive patterns).
-- Ordering is valid (001, 002, 003).
-- But migration 002 contains a SQL syntax error.
-- The error is caught when the DB engine tries to execute it.
-- Migration 001 is already committed (PostgreSQL rolled it back).
-- Migration 002 is rolled back entirely. 003 never runs.
--
-- Run with:
--   safedb validate --db-type postgres --ci \
--     --migrations-path ./examples/05_execution_fail
--
-- Expected error:
--   Postgres migration failed (v2 - 002_broken_syntax.sql):
--   syntax error at or near "GIBBERISH"
-- ============================================================

CREATE TABLE accounts (
    id       SERIAL PRIMARY KEY,
    name     VARCHAR(100) NOT NULL UNIQUE,
    balance  NUMERIC(12, 2) NOT NULL DEFAULT 0
);
