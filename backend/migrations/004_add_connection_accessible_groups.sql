-- Phase 1: Connection Accessibility Discovery
-- Tracks which groups each Telegram connection can access.
-- Used for auto-assigning multi-connection admins.

CREATE TABLE IF NOT EXISTS connection_accessible_groups (
    id BIGSERIAL PRIMARY KEY,
    connection_id UUID NOT NULL REFERENCES telegram_connections(id) ON DELETE CASCADE,
    group_id BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(connection_id, group_id)
);

CREATE INDEX IF NOT EXISTS idx_connection_accessible_groups_connection_id
    ON connection_accessible_groups(connection_id);

CREATE INDEX IF NOT EXISTS idx_connection_accessible_groups_group_id
    ON connection_accessible_groups(group_id);

CREATE INDEX IF NOT EXISTS idx_connection_accessible_groups_discovered_at
    ON connection_accessible_groups(discovered_at DESC);

-- Comment for documentation
COMMENT ON TABLE connection_accessible_groups IS
    'Stores which groups each Telegram connection can access. '
    'Populated by live_crawler.discover_group_accessibility() at startup. '
    'Used by backfill_connection_ids() to auto-assign groups to connections for multi-connection admins.';
