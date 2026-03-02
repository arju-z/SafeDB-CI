-- 004_create_orders.sql
-- PURPOSE: Create the orders and order_items tables.
-- An order is a record of a user's purchase intent. It contains line items
-- that reference specific products. These two tables are created together
-- because order_items has a strict FK dependency on orders.

-- WHY SEPARATE FROM PRODUCTS MIGRATION:
-- Orders depend on both users and products. This migration can only
-- run after 001 (users) and 003 (products) have been applied.

CREATE TYPE order_status AS ENUM (
    'pending',
    'confirmed',
    'shipped',
    'delivered',
    'cancelled'
);

CREATE TABLE orders (
    id          SERIAL PRIMARY KEY,

    -- The user who placed this order.
    -- ON DELETE RESTRICT prevents deleting a user who has orders.
    -- WHY RESTRICT (not CASCADE): Deleting an order history is a compliance
    -- risk in most jurisdictions. We prevent it at the DB layer.
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,

    status      order_status NOT NULL DEFAULT 'pending',

    -- total_amount is denormalized here for fast reporting queries.
    -- The authoritative calculation is done via order_items at checkout.
    total_amount NUMERIC(12, 2) NOT NULL CHECK (total_amount >= 0),

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index on user_id for efficient per-user order history queries.
-- WHY EXPLICIT INDEX: A FK constraint does NOT implicitly create an index
-- in PostgreSQL. Without this, querying orders by user requires a full table scan.
CREATE INDEX idx_orders_user_id ON orders (user_id);

CREATE TABLE order_items (
    id          SERIAL PRIMARY KEY,

    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,

    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,

    -- quantity must be at least 1.
    quantity    INTEGER NOT NULL CHECK (quantity > 0),

    -- unit_price captures the price at time of purchase.
    -- Product prices can change after the fact; this preserves the sale price.
    unit_price  NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0)
);

-- Composite index for looking up all items in a given order.
CREATE INDEX idx_order_items_order_id ON order_items (order_id);
