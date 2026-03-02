-- examples/broken_schema/003_create_shipments.sql
--
-- ⛔ EXPECTED OUTCOME: Passes Phase 2 (safety), passes Phase 3 (execution),
--    but is BLOCKED at Phase 5 (Schema Structural Validation) — exit 1.
--
-- This simulates a subtle authoring mistake: the migration runs without error
-- on the CI DB because constraints are allowed under some conditions, but the
-- relational structure is semantically broken.
--
-- STRUCTURAL VIOLATIONS PLANTED:
--
--   [HIGH] FK references a non-existent table ('order_items' does not exist).
--          The developer typed the wrong table name — a common copy-paste error.
--          SafeDB-CI will catch this post-execution via catalog inspection.
--
--   [HIGH] FK references 'orders.status' — a column with no UNIQUE constraint
--          and is not a primary key. PostgreSQL actually rejects this at
--          constraint-creation time, so this migration will ALSO fail
--          execution (Phase 3) before even reaching schema validation.
--          This demonstrates that the safety and schema layers are complementary.
--
-- HOW TO TEST PHASE 5 IN ISOLATION:
--   Simplify this file to only the 'order_items_ref' FK (non-existent table),
--   which PostgreSQL allows via DEFERRABLE constraints in some configurations.
--   The schema validator will still catch it by reading the catalog.

CREATE TABLE shipments (
    id          SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),

    -- BUG: 'order_items' table does not exist anywhere in this migration set.
    -- This is a dangling reference — a clear structural defect.
    order_item_id INTEGER REFERENCES order_items(id),

    shipped_at  TIMESTAMPTZ
);
