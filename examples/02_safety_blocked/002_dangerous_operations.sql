-- ============================================================
-- SCENARIO 2: SAFETY BLOCKED
-- ⚠ THIS FILE CONTAINS INTENTIONALLY DANGEROUS SQL FOR TESTING ⚠
--
-- 002_dangerous_operations.sql
-- This migration contains multiple HIGH severity patterns.
-- SafeDB-CI will detect all of them in Phase 2 (static analysis)
-- and halt before ANY migration is sent to the database.
--
-- Detected violations:
--   [HIGH] DROP TABLE     → irrecoverable data loss
--   [HIGH] TRUNCATE       → deletes all rows, no transaction log
--   [HIGH] DELETE without WHERE → full-table wipe
-- ============================================================

-- VIOLATION 1: DROP TABLE
-- Destroys the users table and all its data permanently.
-- No transaction can recover this in a live system.
DROP TABLE users;

-- VIOLATION 2: TRUNCATE
-- Wipes every row from whatever orders table exists.
-- Faster than DELETE, precisely because it bypasses the transaction log.
TRUNCATE TABLE orders;

-- VIOLATION 3: DELETE without WHERE clause
-- Deletes every row in the sessions table.
-- Missing WHERE means there is no targeted scope — this is a full wipe.
DELETE FROM sessions;

-- SafeDB-CI halts after detecting the first scan pass over all files.
-- It reports ALL violations at once so you can fix everything in a single pass.
