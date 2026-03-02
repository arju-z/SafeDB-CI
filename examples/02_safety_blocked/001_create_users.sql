-- ============================================================
-- SCENARIO 2: SAFETY BLOCKED
-- Expected outcome: PHASE 2 FAILS — exit 1, NO DB CONTACT MADE
--
-- The safety scanner detects HIGH severity patterns and halts
-- immediately. Migrations are never sent to the database.
--
-- Run with:
--   safedb validate --db-type postgres --ci \
--     --migrations-path ./examples/02_safety_blocked
-- ============================================================

-- 001_create_users.sql  (clean — passes safety)
-- This migration is fine. The safety block happens in 002.

CREATE TABLE users (
    id         SERIAL PRIMARY KEY,
    username   VARCHAR(100) NOT NULL UNIQUE,
    email      VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
