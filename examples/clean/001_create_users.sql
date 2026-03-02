-- examples/clean/001_create_users.sql
-- OUTCOME: PASS — Phase 1, 2, 3, 4, 5 all pass.
-- Creates a well-formed users table with a PK, unique email, and UTC timestamps.

CREATE TABLE users (
    id         SERIAL PRIMARY KEY,
    email      VARCHAR(255) NOT NULL UNIQUE,
    username   VARCHAR(100) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
