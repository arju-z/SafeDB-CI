-- ============================================================
-- SCENARIO 4: ORDERING VIOLATION
-- Expected outcome: PHASE 1 FAILS — exit 1, immediately
--
-- The versioning check runs before EVERYTHING — before safety,
-- before DB connection, before execution. A sequence gap or
-- duplicate version number is a hard error because it signals
-- a missing or mismerged migration that could leave production
-- in an undefined state.
--
-- This folder has: 001, 002, 004 — version 003 is intentionally MISSING.
--
-- Run with:
--   safedb validate --db-type postgres --ci \
--     --migrations-path ./examples/04_ordering_fail
--
-- Expected error:
--   MigrationOrderingError: Expected version 003, but got 004
-- ============================================================

CREATE TABLE users (
    id       SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    email    VARCHAR(255) NOT NULL UNIQUE
);
