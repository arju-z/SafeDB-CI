-- ============================================================
-- SCENARIO 3: SCHEMA INTEGRITY FAIL
-- 002_create_metrics.sql
--
-- A second table also created without a PRIMARY KEY.
-- Additionally, this table has a DUPLICATE FK constraint —
-- the same column mapped to the same target twice (a copy-paste error).
--
-- STRUCTURAL DEFECTS IN THIS FILE:
--   [MEDIUM] Table 'metrics' has no PRIMARY KEY
--   [MEDIUM] Duplicate FK constraint: source_id -> events.occurred_at (twice)
--
-- Both execute without error. Both are caught by Phase 5 in strict mode.
-- ============================================================

-- Note: metrics also lacks a PRIMARY KEY (another MEDIUM anomaly).
-- The schema validator accumulates ALL anomalies before reporting —
-- you'll see a complete report, not just the first violation found.
CREATE TABLE metrics (
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metric_name  VARCHAR(100) NOT NULL,
    value        NUMERIC NOT NULL
);
