-- ============================================================
-- SCENARIO 7: DRY-RUN MODE
-- Expected outcome: Phases 1–3 run, SQL validated, NO state committed
--
-- Run with:
--   safedb validate --db-type postgres --ci --dry-run \
--     --migrations-path ./examples/07_dry_run
--
-- After running, verify nothing was committed:
--   docker exec safedb_postgres psql -U safedb -d safedb_test \
--     -c "\dt" | grep inventory
--   (Should return nothing — tables were rolled back)
--
-- Run TWICE: second run should behave identically.
-- In normal mode, second run would fail (tables already exist).
-- ============================================================

CREATE TABLE inventory (
    id          SERIAL PRIMARY KEY,
    sku         VARCHAR(50) NOT NULL UNIQUE,
    name        VARCHAR(200) NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    unit_price  NUMERIC(10, 2) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
