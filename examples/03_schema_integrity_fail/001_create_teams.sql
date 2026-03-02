-- ============================================================
-- SCENARIO 3: SCHEMA INTEGRITY FAIL (strict mode required)
-- Expected outcome: PHASES 1–3 PASS, PHASE 5 FAILS — exit 1
--
-- All SQL is syntactically valid and executes without error.
-- No destructive patterns (passes Phase 2).
-- BUT: two tables are created without PRIMARY KEYS, and one table
-- has a duplicate FK constraint. These structural defects are
-- invisible to the database engine but detected by reading
-- information_schema in Phase 5.
--
-- With --strict flag, MEDIUM anomalies become hard failures.
--
-- Run with (MUST include --strict to see exit 1):
--   safedb validate --db-type postgres --ci --strict \
--     --migrations-path ./examples/03_schema_integrity_fail
-- ============================================================

-- 001_create_events.sql
-- An events log table intentionally written WITHOUT a PRIMARY KEY.
-- This is the structural defect. The migration executes fine —
-- Postgres does not require a PK. But every production table should
-- have one for replication, ORM support, and FK referencing.

CREATE TABLE events (
    -- Deliberately omitting: id SERIAL PRIMARY KEY
    -- The table will be created, migrations will run, but the schema
    -- validator will flag this as a MEDIUM anomaly: "Table missing PRIMARY KEY"
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type   VARCHAR(100) NOT NULL,
    payload      JSONB
);
