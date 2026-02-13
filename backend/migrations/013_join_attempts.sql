-- Migration 013: Auto-Join Feature - Join Attempts Tracking Table
-- Purpose: Track all group join attempts (success/failure) for smart connection selection
-- and analytics. Enables FloodWait-aware intelligent account selection.

-- Create join_attempts table
CREATE TABLE IF NOT EXISTS join_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Connection that attempted the join
    connection_id UUID NOT NULL REFERENCES telegram_connections(id) ON DELETE CASCADE,
    telegram_user_id BIGINT NOT NULL,  -- Telegram user ID (for quick lookup)

    -- Target group identifier (one must be present)
    group_link TEXT,      -- t.me/joinchat/ABC or full URL
    group_username TEXT,  -- @username (without @)

    -- Result (populated on success)
    group_id BIGINT REFERENCES groups(id) ON DELETE SET NULL,  -- NULL if failed before getting ID

    -- Attempt status
    success BOOLEAN NOT NULL DEFAULT FALSE,

    -- Error details (if failed)
    error_type TEXT,  -- 'flood_wait', 'invite_expired', 'privacy', 'unknown', etc.
    flood_wait_seconds INTEGER,  -- If error_type = 'flood_wait', how long to wait

    -- Timestamp
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraint: at least one identifier must be provided
    CONSTRAINT join_attempts_group_identifier_check
        CHECK (group_link IS NOT NULL OR group_username IS NOT NULL)
);

-- Performance indexes
-- 1. Query recent attempts by connection (for rate limiting)
CREATE INDEX idx_join_attempts_connection_time
    ON join_attempts(connection_id, attempted_at DESC);

-- 2. Query attempts by Telegram user ID (for health tracking)
CREATE INDEX idx_join_attempts_telegram_user_time
    ON join_attempts(telegram_user_id, attempted_at DESC);

-- 3. Query only successful joins (for analytics)
CREATE INDEX idx_join_attempts_success_time
    ON join_attempts(success, attempted_at DESC)
    WHERE success = true;

-- 4. Cleanup old records efficiently (keep 7 days)
CREATE INDEX idx_join_attempts_cleanup
    ON join_attempts(attempted_at)
    WHERE attempted_at < NOW() - INTERVAL '7 days';

-- 5. Lookup by group (find all join attempts for a specific group)
CREATE INDEX idx_join_attempts_group_id
    ON join_attempts(group_id, attempted_at DESC)
    WHERE group_id IS NOT NULL;

-- Add table comment
COMMENT ON TABLE join_attempts IS
'Tracks all Telegram group join attempts for auto-join feature. Used for smart connection selection (avoiding FloodWait) and analytics.';

COMMENT ON COLUMN join_attempts.connection_id IS
'UUID of the telegram_connection that attempted the join';

COMMENT ON COLUMN join_attempts.telegram_user_id IS
'Telegram user ID (from get_me()) for faster lookups without JOIN';

COMMENT ON COLUMN join_attempts.group_link IS
'Full Telegram link (t.me/joinchat/ABC or https://t.me/+XYZ) if join was via invite link';

COMMENT ON COLUMN join_attempts.group_username IS
'Group username (without @) if join was via username';

COMMENT ON COLUMN join_attempts.group_id IS
'Reference to groups table if join succeeded and group was registered';

COMMENT ON COLUMN join_attempts.error_type IS
'Error category: flood_wait, invite_expired, invite_invalid, privacy, admin_required, username_invalid, unknown';

COMMENT ON COLUMN join_attempts.flood_wait_seconds IS
'Number of seconds to wait if error_type = flood_wait (extracted from Telethon exception)';
