-- examples/clean/003_create_posts.sql
-- OUTCOME: PASS — posts table referencing users via FK to the PK column.
-- Demonstrates a proper one-to-many with index on the FK column.

CREATE TABLE posts (
    id         SERIAL PRIMARY KEY,
    author_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    title      VARCHAR(255) NOT NULL,
    body       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Explicit index on FK column — PostgreSQL does NOT create this automatically.
CREATE INDEX idx_posts_author_id ON posts (author_id);
