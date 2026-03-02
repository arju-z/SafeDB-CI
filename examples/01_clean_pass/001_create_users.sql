-- ============================================================
-- SCENARIO 1: CLEAN PASS
-- Expected outcome: ALL 6 PHASES PASS — exit 0
--
-- Run with:
--   safedb validate --db-type postgres --ci \
--     --migrations-path ./examples/01_clean_pass
-- ============================================================

-- 001_create_users.sql
-- A clean, well-formed table with explicit PK and UNIQUE constraints.
-- No dangerous SQL. All FK targets will resolve correctly.

CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(100) NOT NULL UNIQUE,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
