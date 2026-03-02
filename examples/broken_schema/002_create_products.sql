-- examples/broken_schema/002_create_products.sql
-- OUTCOME: Executes cleanly. No safety violations.
-- Creates a products table with no primary key defined.
--
-- STRUCTURAL DEFECT PLANTED:
--   Missing PRIMARY KEY — schema validator will flag this as MEDIUM severity.
--   In strict mode, this alone will fail the pipeline.

CREATE TABLE products (
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    price       NUMERIC(10, 2) NOT NULL
    -- Intentionally no PRIMARY KEY defined
);
