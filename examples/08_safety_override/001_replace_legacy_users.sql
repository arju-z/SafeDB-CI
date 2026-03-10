-- ============================================================
-- SCENARIO 8: SAFETY OVERRIDE — safedb:allow ANNOTATION
-- Expected outcome: Phase 2 passes (exit 0), override is logged
--
-- Run with:
--   safedb validate --db-type postgres --ci \
--     --migrations-path ./examples/08_safety_override
--
-- This scenario demonstrates intentional use of the safedb:allow
-- annotation to approve a genuinely necessary destructive operation
-- that has been reviewed and accepted by the team.
--
-- Without safedb:allow, this file would FAIL Phase 2 (safety scan)
-- because DROP TABLE is a HIGH severity violation. The annotation
-- signals to SafeDB-CI that this destruction was explicitly reviewed.
-- ============================================================

-- Step 1: First create a proper replacement table.
-- The migration strategy is: create-new, migrate-data (app-side), drop-old.
-- This migration only handles the schema side of that three-step process.

CREATE TABLE users (
    id         SERIAL PRIMARY KEY,
    username   VARCHAR(100) NOT NULL UNIQUE,
    email      VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Step 2: Drop the legacy table that `users` is replacing.
-- This is a data-loss operation. The team has verified:
--   a) All data has been migrated to the new `users` table already.
--   b) This DROP has been reviewed and approved in PR #142.
--   c) A pre-deployment backup was taken on 2026-03-10.
-- safedb:allow
DROP TABLE IF EXISTS legacy_user_accounts;
