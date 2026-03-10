-- ============================================================
-- SCENARIO 6: NAMING HEURISTICS WARNINGS
-- Expected outcome: Phase 5b fires multiple MEDIUM warnings
--
-- Without --strict: warnings printed, exit 0
-- With --strict:    warnings become hard failures, exit 1
--
-- Run with:
--   safedb validate --db-type postgres --ci \
--     --migrations-path ./examples/06_naming_warnings
--
-- Run with strict:
--   safedb validate --db-type postgres --ci --strict \
--     --migrations-path ./examples/06_naming_warnings
-- ============================================================

-- 001_create_departments.sql
-- DEFECT 1: `manager_id` column with no FK constraint to any table.
-- The naming heuristic will flag: "Orphaned _id column (missing FK)"
-- This simulates a developer who meant to add a FK but forgot.

CREATE TABLE departments (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    -- manager_id looks like a FK to employees or users, but has no constraint.
    -- This is the most common normalization debt pattern: a column named X_id
    -- with no FK declaration, leaving the relationship unenforced at DB level.
    manager_id  INTEGER NOT NULL,
    budget      NUMERIC(12, 2) NOT NULL DEFAULT 0
);
