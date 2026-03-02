-- 002_create_roles.sql
-- PURPOSE: Create the roles lookup table and the user_roles join table.
-- Roles define system-level permissions (admin, viewer, editor, etc).
-- This is a separate migration from users because roles are a distinct
-- domain concept that may change independently.

CREATE TABLE roles (
    id          SERIAL PRIMARY KEY,

    -- name is the canonical identifier for a role (e.g. 'admin', 'viewer').
    -- It must be unique. We lowercase-enforce this at the application layer.
    name        VARCHAR(50) NOT NULL UNIQUE,

    -- description is optional human-readable context for the role.
    description TEXT,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- user_roles is the many-to-many join table between users and roles.
-- WHY COMPOSITE PK: The pair (user_id, role_id) is the natural key.
-- A user cannot be assigned the same role twice.
CREATE TABLE user_roles (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id    INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (user_id, role_id)
);
