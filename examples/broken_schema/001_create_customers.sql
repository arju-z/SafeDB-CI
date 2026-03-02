-- examples/broken_schema/001_create_customers.sql
-- OUTCOME: Executes cleanly. No safety violations.
-- Creates two tables that look fine individually.

CREATE TABLE customers (
    id    SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE
);

-- NOTE: orders.status has NO unique constraint and is NOT a primary key.
-- This will become the target of a broken FK in migration 003.
CREATE TABLE orders (
    id       SERIAL PRIMARY KEY,
    status   VARCHAR(50) NOT NULL DEFAULT 'pending',
    total    NUMERIC(10, 2) NOT NULL
);
