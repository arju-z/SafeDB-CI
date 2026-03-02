-- ============================================================
-- SCENARIO 2: SAFETY BLOCKED
-- 003_never_runs.sql
-- This migration is never reached.
-- SafeDB-CI scans ALL files for safety violations first,
-- then halts if any HIGH severity patterns are found.
-- It does not execute any migration before completing the full scan.
-- So this file is loaded but never sent to the database.
-- ============================================================

CREATE TABLE comments (
    id      SERIAL PRIMARY KEY,
    body    TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id)
);
