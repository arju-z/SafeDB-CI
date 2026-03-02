-- 006_create_sessions.sql
-- PURPOSE: Create the user session tracking table.
-- Stores active authentication tokens with TTL metadata.
-- WHY A TABLE (not Redis): For this system, sessions need to be auditable,
-- revocable by admin, and survive application restarts. A DB-backed session
-- store provides all three without additional infrastructure.

CREATE TABLE sessions (
    id            BIGSERIAL PRIMARY KEY,

    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- token is the opaque bearer token issued to the client.
    -- It is stored as a SHA-256 hash, never the raw value.
    -- UNIQUE enforces that no two sessions share the same token hash.
    token_hash    VARCHAR(64) NOT NULL UNIQUE,

    -- ip_address and user_agent are stored for security audit purposes.
    ip_address    VARCHAR(45),   -- IPv6 max length is 45 chars
    user_agent    TEXT,

    -- expires_at is set by the application at session creation time.
    -- Expired sessions are cleaned up by a scheduled job, not deleted on logout.
    -- WHY NOT DELETE ON LOGOUT: Preserving expired sessions lets the audit
    -- system detect suspicious token reuse after logout.
    expires_at    TIMESTAMPTZ NOT NULL,

    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- revoked_at is set when a session is explicitly terminated (logout, admin revoke).
    -- NULL means the session is still active (assuming not expired).
    revoked_at    TIMESTAMPTZ
);

-- Index for fast token lookup during request authentication middleware.
-- This is the hot path; every authenticated API request queries this index.
CREATE INDEX idx_sessions_token_hash ON sessions (token_hash);

-- Index for admin operations: "revoke all sessions for user X".
CREATE INDEX idx_sessions_user_id ON sessions (user_id);
