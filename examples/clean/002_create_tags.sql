-- examples/clean/002_create_tags.sql
-- OUTCOME: PASS — clean many-to-many between users and tags.
-- Demonstrates a composite PK join table with valid FK references.

CREATE TABLE tags (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE user_tags (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, tag_id)
);
