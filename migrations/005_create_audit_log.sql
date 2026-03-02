-- 005_create_audit_log.sql
-- PURPOSE: Create an append-only audit log table.
-- Records all significant state changes across the system.
-- WHY APPEND-ONLY: An audit log must be tamper-evident. The application
-- should only ever INSERT into this table, never UPDATE or DELETE.
-- DB-level enforcement of this is done via a trigger (not in scope here).

CREATE TABLE audit_log (
    id          BIGSERIAL PRIMARY KEY,

    -- actor_id references the user who performed the action.
    -- ON DELETE SET NULL: If the user is deleted, the audit record is preserved
    -- but the actor becomes anonymous. We NEVER delete audit records.
    actor_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,

    -- entity_type describes what kind of object was changed (e.g. 'order', 'user').
    entity_type VARCHAR(100) NOT NULL,

    -- entity_id is the PK of the changed row.
    entity_id   INTEGER NOT NULL,

    -- action describes what happened: 'created', 'updated', 'deleted', 'status_changed'.
    action      VARCHAR(50) NOT NULL,

    -- payload stores a JSON snapshot of old/new values for the changed fields.
    -- JSONB (binary JSON) is used over JSON for indexed query support.
    payload     JSONB,

    -- occurred_at is explicitly provided by the application, not DEFAULT NOW().
    -- WHY: In batch operations, we want the actual event time, not the insert time.
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Composite index for querying the audit history of a specific entity.
-- e.g. "Show me all changes to order #1234"
CREATE INDEX idx_audit_log_entity ON audit_log (entity_type, entity_id);

-- Index for querying all actions performed by a specific user.
CREATE INDEX idx_audit_log_actor ON audit_log (actor_id);
