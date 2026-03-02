-- 003_create_products.sql
-- PURPOSE: Create the products catalog table.
-- Products are independent of users: they represent the things being sold.
-- This migration is intentionally separate so the products domain can evolve
-- independently without coupling to user or order migrations.

CREATE TABLE products (
    id          SERIAL PRIMARY KEY,

    -- SKU (Stock Keeping Unit) uniquely identifies a product variant.
    -- Indexed via UNIQUE for fast catalog lookups.
    sku         VARCHAR(100) NOT NULL UNIQUE,

    name        VARCHAR(255) NOT NULL,

    description TEXT,

    -- NUMERIC(10, 2) is the correct type for financial values.
    -- FLOAT would introduce rounding errors (e.g. $19.99 stored as $19.989999...).
    price       NUMERIC(10, 2) NOT NULL CHECK (price >= 0),

    -- stock_qty tracks available inventory. Checked by application before order creation.
    stock_qty   INTEGER NOT NULL DEFAULT 0 CHECK (stock_qty >= 0),

    is_active   BOOLEAN NOT NULL DEFAULT TRUE,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
