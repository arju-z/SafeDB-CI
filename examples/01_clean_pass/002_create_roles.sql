-- SCENARIO 1: CLEAN PASS
-- 002_create_roles.sql
-- Roles lookup table + many-to-many join via user_roles.
-- Composite PK on user_roles prevents duplicate role assignments.

CREATE TABLE roles (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- user_roles is a pure join table — PK is the composite (user_id, role_id).
-- ON DELETE CASCADE is intentional: removing a user removes their role memberships.
CREATE TABLE user_roles (
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id     INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);
