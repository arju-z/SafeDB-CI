-- examples/destructive/003_destroy_everything.sql
--
-- ⛔ EXPECTED OUTCOME: BLOCKED at Phase 2 (Safety Analysis) — exit 1
--    This migration will NEVER be executed against the database.
--    SafeDB-CI will detect ALL of the following violations and halt.
--
-- VIOLATIONS DETECTED:
--   [HIGH] TRUNCATE        — wipes all rows, no transaction log
--   [HIGH] DROP TABLE      — irrecoverable data loss
--   [HIGH] DELETE (no WHERE) — full table wipe
--   [HIGH] DROP COLUMN     — permanently removes column and its data
--   [MEDIUM] CASCADE       — blast-radius warning on the DROP
--   [MEDIUM] ALTER COLUMN TYPE — may silently truncate data
--
-- This simulates what happens when a developer accidentally includes
-- cleanup or reset logic meant for a local dev environment.

-- Attempt 1: Wipe all transactions without a condition
TRUNCATE TABLE transactions;

-- Attempt 2: Delete all accounts with no filter
DELETE FROM accounts;

-- Attempt 3: Drop the entire transactions table
DROP TABLE transactions CASCADE;

-- Attempt 4: Remove a column from accounts
ALTER TABLE accounts DROP COLUMN balance;

-- Attempt 5: Change balance type (would silently truncate extra digits)
ALTER TABLE accounts ALTER COLUMN username TYPE TEXT;
