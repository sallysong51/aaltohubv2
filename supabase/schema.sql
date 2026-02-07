-- ⚠️  DEPRECATED — DO NOT USE
-- This file is superseded by schema_actual.sql which is the single source of truth.
-- This file used UUID for users.id, but the application uses BIGSERIAL.
-- This file has auth.uid()-based RLS policies that don't work with custom JWT auth.
-- Kept for historical reference only.
--
-- AaltoHub v2 Database Schema (DEPRECATED)
-- Supabase PostgreSQL Schema

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- Users Table
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id BIGINT UNIQUE NOT NULL,
    phone_number TEXT,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast telegram_id lookup
CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- ============================================================
-- Telethon Sessions Table (Encrypted)
-- ============================================================
CREATE TABLE IF NOT EXISTS telethon_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_data TEXT NOT NULL, -- Encrypted session string
    key_hash TEXT NOT NULL, -- Hash of encryption key for validation
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id)
);

-- ============================================================
-- Groups Table
-- ============================================================
-- NOTE: Code uses db.table("groups") with id = telegram group ID (BIGINT).
-- The id column stores the Telegram group ID directly (not a UUID).
CREATE TABLE IF NOT EXISTS groups (
    id BIGINT PRIMARY KEY,              -- telegram group ID used directly as PK
    title TEXT NOT NULL,
    username TEXT,
    member_count INTEGER,
    group_type TEXT CHECK (group_type IN ('group', 'supergroup', 'channel')),
    visibility TEXT NOT NULL DEFAULT 'public' CHECK (visibility IN ('public', 'private')),
    crawl_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    crawl_status TEXT,
    last_crawled_at TIMESTAMPTZ,
    last_error TEXT,
    invite_link TEXT,
    registered_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_groups_visibility ON groups(visibility);
CREATE INDEX IF NOT EXISTS idx_groups_crawl_enabled ON groups(crawl_enabled) WHERE crawl_enabled = TRUE;
CREATE INDEX IF NOT EXISTS idx_groups_registered_by ON groups(registered_by);

-- ============================================================
-- User Groups Table (group membership / following)
-- ============================================================
-- NOTE: Code uses db.table("user_groups")
CREATE TABLE IF NOT EXISTS user_groups (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, group_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_user_groups_user_id ON user_groups(user_id);
CREATE INDEX IF NOT EXISTS idx_user_groups_group_id ON user_groups(group_id);

-- ============================================================
-- Messages Table (partitioned by sent_at for retention performance)
-- ============================================================
CREATE TABLE IF NOT EXISTS messages (
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    telegram_message_id BIGINT NOT NULL,
    group_id BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    sender_id BIGINT,
    sender_name TEXT,
    sender_username TEXT,
    content TEXT,
    media_type TEXT DEFAULT 'text' CHECK (media_type IN ('text', 'photo', 'video', 'document', 'audio', 'sticker', 'voice', 'video_note')),
    media_url TEXT,
    media_thumbnail_url TEXT,
    reply_to_message_id BIGINT,
    topic_id INTEGER,
    topic_title TEXT,
    is_deleted BOOLEAN DEFAULT FALSE,
    edited_at TIMESTAMPTZ,
    edit_count INTEGER DEFAULT 0,
    sent_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (id, sent_at),
    UNIQUE(telegram_message_id, group_id, sent_at)
) PARTITION BY RANGE (sent_at);

-- Default partition catches all rows (simplest approach for 14-day retention)
CREATE TABLE IF NOT EXISTS messages_default PARTITION OF messages DEFAULT;

-- Indexes for fast queries (created on partitioned table, auto-applied to partitions)
CREATE INDEX IF NOT EXISTS idx_messages_group_id ON messages(group_id);
CREATE INDEX IF NOT EXISTS idx_messages_sent_at ON messages(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_telegram_message_id ON messages(telegram_message_id);
CREATE INDEX IF NOT EXISTS idx_messages_topic_id ON messages(topic_id) WHERE topic_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_messages_not_deleted ON messages(group_id, sent_at DESC) WHERE is_deleted = FALSE;
CREATE INDEX IF NOT EXISTS idx_messages_retention ON messages(sent_at) WHERE sent_at IS NOT NULL;

-- Full-text search index on message content
CREATE INDEX IF NOT EXISTS idx_messages_content_fts ON messages USING GIN (to_tsvector('english', content));

-- ============================================================
-- Crawler Status Table
-- ============================================================
CREATE TABLE IF NOT EXISTS crawler_status (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'inactive' CHECK (status IN ('active', 'inactive', 'error', 'initializing')),
    last_message_at TIMESTAMPTZ,
    last_error TEXT,
    error_count INTEGER DEFAULT 0,
    is_enabled BOOLEAN DEFAULT TRUE,
    initial_crawl_progress INTEGER DEFAULT 0,
    initial_crawl_total INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(group_id)
);

-- Index
CREATE INDEX IF NOT EXISTS idx_crawler_status_group_id ON crawler_status(group_id);
CREATE INDEX IF NOT EXISTS idx_crawler_status_status ON crawler_status(status);

-- ============================================================
-- Crawler Error Logs Table
-- ============================================================
CREATE TABLE IF NOT EXISTS crawler_error_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id BIGINT REFERENCES groups(id) ON DELETE SET NULL,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    error_details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index
CREATE INDEX IF NOT EXISTS idx_crawler_error_logs_created_at ON crawler_error_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_crawler_error_logs_group_id ON crawler_error_logs(group_id);

-- ============================================================
-- Private Group Invites Table
-- ============================================================
CREATE TABLE IF NOT EXISTS private_group_invites (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    token TEXT UNIQUE NOT NULL,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ,
    is_revoked BOOLEAN DEFAULT FALSE,
    revoked_at TIMESTAMPTZ,
    used_count INTEGER DEFAULT 0,
    max_uses INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index
CREATE INDEX IF NOT EXISTS idx_private_group_invites_token ON private_group_invites(token);
CREATE INDEX IF NOT EXISTS idx_private_group_invites_group_id ON private_group_invites(group_id);

-- ============================================================
-- Row Level Security (RLS) Policies
-- ============================================================

-- Enable RLS on all tables
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE telethon_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE crawler_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE crawler_error_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE private_group_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_groups ENABLE ROW LEVEL SECURITY;

-- Users: Users can read their own data, admins can read all
CREATE POLICY "Users can read own data" ON users
    FOR SELECT
    USING (auth.uid()::text = id::text OR
           EXISTS (SELECT 1 FROM users WHERE id::text = auth.uid()::text AND role = 'admin'));

-- Telethon Sessions: Users can only access their own sessions
CREATE POLICY "Users can access own sessions" ON telethon_sessions
    FOR ALL
    USING (user_id::text = auth.uid()::text);

-- Groups: Public groups readable by all, private by authorized users
CREATE POLICY "Public groups readable by authenticated users" ON groups
    FOR SELECT
    USING (visibility = 'public' OR
           EXISTS (SELECT 1 FROM user_groups WHERE user_id::text = auth.uid()::text AND group_id = groups.id));

-- Messages: Accessible based on group visibility
CREATE POLICY "Messages readable based on group access" ON messages
    FOR SELECT
    USING (EXISTS (
        SELECT 1 FROM groups
        WHERE groups.id = messages.group_id
        AND (visibility = 'public' OR
             EXISTS (SELECT 1 FROM user_groups WHERE user_id::text = auth.uid()::text AND group_id = groups.id))
    ));

-- Crawler Status: Readable by all authenticated, writable by service role
CREATE POLICY "Crawler status readable by authenticated" ON crawler_status
    FOR SELECT
    USING (auth.role() = 'authenticated');

-- Crawler Error Logs: Readable by admins only
CREATE POLICY "Crawler errors readable by admins" ON crawler_error_logs
    FOR SELECT
    USING (EXISTS (SELECT 1 FROM users WHERE id::text = auth.uid()::text AND role = 'admin'));

-- ============================================================
-- Functions and Triggers
-- ============================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply updated_at trigger to relevant tables
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_telethon_sessions_updated_at BEFORE UPDATE ON telethon_sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_groups_updated_at BEFORE UPDATE ON groups
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_crawler_status_updated_at BEFORE UPDATE ON crawler_status
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Message Retention Cleanup Function (14-day policy)
-- ============================================================
-- Can be called manually or via pg_cron (if available):
--   SELECT cron.schedule('cleanup-old-messages', '0 * * * *',
--     $$SELECT cleanup_old_messages()$$);

CREATE OR REPLACE FUNCTION cleanup_old_messages()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM messages
    WHERE sent_at < NOW() - INTERVAL '14 days';

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- Realtime Publications (for Supabase Realtime)
-- ============================================================

-- Enable realtime for crawler_status table
-- NOTE: messages use Supabase Broadcast API (pushed from backend) instead of
-- Postgres Changes (WAL replication) to avoid single-thread WAL bottleneck.
ALTER PUBLICATION supabase_realtime ADD TABLE crawler_status;
