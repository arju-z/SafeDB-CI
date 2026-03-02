-- SCENARIO 4: ORDERING VIOLATION
-- 004_create_orders.sql
--
-- ⚠ VERSION GAP: This is 004 but 003 is missing from the folder.
--
-- SafeDB-CI loads all .sql files sorted by version prefix,
-- then checks that the sequence is strictly 001, 002, 003...
-- Finding 004 where 003 is expected immediately raises:
--
--   MigrationOrderingError
--
-- No database connection is opened. No SQL is executed.
-- The pipeline halts at Phase 1.
--
-- WHY THIS MATTERS IN PRODUCTION:
-- A version gap means a migration file was deleted, renamed,
-- or never committed. The production DB may be running version 003
-- which we never validated. Deploying 004 on top of an unknown
-- 003 is undefined behavior. SafeDB-CI refuses to proceed.

CREATE TABLE orders (
    id      SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    amount  NUMERIC(10, 2) NOT NULL
);
