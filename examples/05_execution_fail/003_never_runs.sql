-- SCENARIO 5: EXECUTION FAILURE
-- 003_never_runs.sql
--
-- This migration is syntactically valid and logically correct.
-- It never executes because 002 failed and the pipeline halted.
-- This demonstrates that SafeDB-CI stops at the first execution
-- failure — subsequent migrations in the sequence are not attempted.

CREATE TABLE ledger_entries (
    id             SERIAL PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    note           TEXT,
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
