-- SCENARIO 1: CLEAN PASS
-- 003_create_posts.sql
-- Posts table with a well-formed FK back to users.
-- The FK target (users.id) is a PRIMARY KEY — structural validation will pass.

CREATE TABLE posts (
    id          SERIAL PRIMARY KEY,
    author_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    title       VARCHAR(300) NOT NULL,
    body        TEXT NOT NULL,
    published   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index on author_id for fast per-user post listing queries.
-- PostgreSQL does NOT implicitly index FK columns — this is required.
CREATE INDEX idx_posts_author_id ON posts (author_id);
