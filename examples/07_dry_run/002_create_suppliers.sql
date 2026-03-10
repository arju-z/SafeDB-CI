-- SCENARIO 7: DRY-RUN MODE
-- 002_create_suppliers.sql
-- A well-formed suppliers table with a FK to inventory.
-- In dry-run, this executes, the FK constraint is validated by PG,
-- then everything is rolled back. Run this 10 times — always clean.

CREATE TABLE suppliers (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(200) NOT NULL UNIQUE,
    email      VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE inventory_suppliers (
    inventory_id INTEGER NOT NULL REFERENCES inventory(id) ON DELETE CASCADE,
    supplier_id  INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    PRIMARY KEY (inventory_id, supplier_id)
);
