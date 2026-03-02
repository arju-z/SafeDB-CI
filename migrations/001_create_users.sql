-- 001_create_users.sql
-- PURPOSE: Create the core users table.
-- Establishes the foundational entity that most other tables will reference.
-- Every FK in subsequent migrations ultimately traces back to this table.

CREATE TABLE users (
    -- SERIAL is PostgreSQL-native auto-increment. Generates a sequence object
    -- automatically. Do NOT use INT AUTO_INCREMENT (MySQL syntax).
    id            SERIAL PRIMARY KEY,

    -- username must be unique across the system.
    -- 100 chars is enough for real usernames without over-allocating.
    username      VARCHAR(100) NOT NULL UNIQUE,

    -- email is required and must be globally unique.
    -- Indexed implicitly via the UNIQUE constraint.
    email         VARCHAR(255) NOT NULL UNIQUE,

    -- password_hash stores the bcrypt/argon2 hash, never the raw password.
    -- 255 chars covers all major hashing algorithms' output lengths.
    password_hash VARCHAR(255) NOT NULL,

    -- is_active allows soft-disabling users without deletion.
    -- Defaults to true since a newly registered user is immediately active.
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,

    -- Timestamps are stored in UTC. Applications handle timezone conversion.
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
