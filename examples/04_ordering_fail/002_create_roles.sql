-- SCENARIO 4: ORDERING VIOLATION
-- 002_create_roles.sql — fine, version sequence continues normally here.

CREATE TABLE roles (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE
);
