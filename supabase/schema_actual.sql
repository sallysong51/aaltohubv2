-- AaltoHub v2 — Canonical Database Schema
-- This is the SINGLE source of truth for the production database.
-- The old schema.sql is DEPRECATED and should not be used.
--
-- Key design decisions:
--   - users.id is BIGSERIAL (not UUID) — matches application code
--   - groups.id is the Telegram group ID directly (BIGINT)
--     NOTE: Telegram supergroup migration changes group IDs. If this happens,
--     a migration script must update groups.id and all FK references.
--     Consider adding a stable internal UUID PK in a future schema revision.
--   - messages table is NOT partitioned (single default partition had zero benefit)
--   - RLS blocks all direct anon access (app uses custom JWT, not Supabase Auth)
--   - Service role key (backend) bypasses RLS automatically

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- Users Table
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    phone_number TEXT,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- telegram_id already has a UNIQUE index; idx_users_telegram_id is redundant — removed
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- ============================================================
-- Admin Credentials Table (Multi-Admin Support)
-- Stores phone numbers and usernames that have admin access
-- ============================================================
CREATE TABLE IF NOT EXISTS admin_credentials (
    id BIGSERIAL PRIMARY KEY,
    phone_number TEXT UNIQUE,
    username TEXT UNIQUE,
    added_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT at_least_one_credential CHECK (
        phone_number IS NOT NULL OR username IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_admin_credentials_phone ON admin_credentials(phone_number) WHERE phone_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_admin_credentials_username ON admin_credentials(username) WHERE username IS NOT NULL;

-- RLS and policies for admin_credentials
ALTER TABLE admin_credentials ENABLE ROW LEVEL SECURITY;

-- Policy: All authenticated users can read (needed for auth checks)
CREATE POLICY IF NOT EXISTS "admin_credentials_readable" ON admin_credentials
    FOR SELECT TO authenticated USING (true);

-- Policy: Only admins can insert
CREATE POLICY IF NOT EXISTS "admin_credentials_admin_insert" ON admin_credentials
    FOR INSERT TO authenticated WITH CHECK (
        EXISTS(SELECT 1 FROM users WHERE id = auth.uid() AND role = 'admin')
    );

-- Policy: Only admins can delete
CREATE POLICY IF NOT EXISTS "admin_credentials_admin_delete" ON admin_credentials
    FOR DELETE TO authenticated USING (
        EXISTS(SELECT 1 FROM users WHERE id = auth.uid() AND role = 'admin')
    );

-- ============================================================
-- Telethon Sessions Table (Encrypted)
-- ============================================================
CREATE TABLE IF NOT EXISTS telethon_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_data TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id)
);

-- ============================================================
-- Groups Table (Telegram Groups)
-- id is the telegram group ID directly (not UUID)
-- ============================================================
CREATE TABLE IF NOT EXISTS groups (
    id BIGINT PRIMARY KEY,  -- This IS the telegram group ID
    name TEXT NOT NULL,
    username TEXT,
    type TEXT CHECK (type IN ('group', 'supergroup', 'channel')),
    photo_url TEXT,
    member_count INTEGER,
    has_topics BOOLEAN DEFAULT FALSE,
    visibility TEXT NOT NULL DEFAULT 'public' CHECK (visibility IN ('public', 'private')),
    invite_link TEXT,
    crawl_status TEXT CHECK (crawl_status IN ('active', 'inactive', 'error')),
    crawl_enabled BOOLEAN DEFAULT FALSE,
    last_crawled_at TIMESTAMPTZ,
    last_error TEXT,
    registered_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_groups_visibility ON groups(visibility);
CREATE INDEX IF NOT EXISTS idx_groups_registered_by ON groups(registered_by);
CREATE INDEX IF NOT EXISTS idx_groups_crawl_enabled ON groups(crawl_enabled) WHERE crawl_enabled = TRUE;

-- ============================================================
-- User Groups (Follower/Access Table)
-- Tracks which users follow/have access to which groups
-- ============================================================
CREATE TABLE IF NOT EXISTS user_groups (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, group_id)
);

CREATE INDEX IF NOT EXISTS idx_user_groups_user_id ON user_groups(user_id);
CREATE INDEX IF NOT EXISTS idx_user_groups_group_id ON user_groups(group_id);

-- ============================================================
-- Messages Table
-- NOT partitioned — single default partition provided zero benefit
-- and forced sent_at into PK/UNIQUE, breaking deduplication.
-- Retention is handled by application-level DELETE + cleanup_old_messages().
-- ============================================================
CREATE TABLE IF NOT EXISTS messages (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    UNIQUE(telegram_message_id, group_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_sender_id ON messages(sender_id) WHERE sender_id IS NOT NULL;

-- Primary query pattern: WHERE group_id = X AND is_deleted = FALSE ORDER BY sent_at DESC
CREATE INDEX IF NOT EXISTS idx_messages_not_deleted ON messages(group_id, sent_at DESC) WHERE is_deleted = FALSE;
-- For retention cleanup: DELETE WHERE sent_at < threshold
CREATE INDEX IF NOT EXISTS idx_messages_retention ON messages(sent_at) WHERE sent_at IS NOT NULL;
-- For topic filtering
CREATE INDEX IF NOT EXISTS idx_messages_topic_id ON messages(topic_id) WHERE topic_id IS NOT NULL;
-- Full-text search index REMOVED — no query uses to_tsvector/@@, and the GIN
-- index adds ~30% write overhead on every INSERT. Re-add when FTS is implemented:
--   CREATE INDEX idx_messages_content_fts ON messages USING GIN (to_tsvector('english', COALESCE(content, '')));

-- ============================================================
-- Private Group Invites Table
-- ============================================================
CREATE TABLE IF NOT EXISTS private_group_invites (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_id BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    token TEXT UNIQUE NOT NULL,
    created_by BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ,
    is_revoked BOOLEAN DEFAULT FALSE,
    revoked_at TIMESTAMPTZ,
    used_count INTEGER DEFAULT 0,
    max_uses INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_private_group_invites_token ON private_group_invites(token);
CREATE INDEX IF NOT EXISTS idx_private_group_invites_group_id ON private_group_invites(group_id);
CREATE INDEX IF NOT EXISTS idx_private_group_invites_expires_at ON private_group_invites(expires_at) WHERE expires_at IS NOT NULL;

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

CREATE INDEX IF NOT EXISTS idx_crawler_error_logs_created_at ON crawler_error_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_crawler_error_logs_group_id ON crawler_error_logs(group_id);

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

-- group_id already has UNIQUE index; no separate index needed
CREATE INDEX IF NOT EXISTS idx_crawler_status_status ON crawler_status(status);

-- ============================================================
-- Entity Cache (Telegram channel_id + access_hash)
-- Prevents repeated get_entity() API calls that cause FloodWaitError
-- ============================================================
CREATE TABLE IF NOT EXISTS entity_cache (
    telegram_id BIGINT PRIMARY KEY,
    access_hash BIGINT NOT NULL DEFAULT 0,
    entity_type TEXT NOT NULL DEFAULT 'channel' CHECK (entity_type IN ('channel', 'chat')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Dead Letter Queue for failed message inserts
-- ============================================================
CREATE TABLE IF NOT EXISTS failed_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_message_id BIGINT,
    group_id BIGINT REFERENCES groups(id) ON DELETE CASCADE,
    payload JSONB NOT NULL,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_failed_messages_created_at ON failed_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_failed_messages_resolved ON failed_messages(resolved) WHERE NOT resolved;
CREATE INDEX IF NOT EXISTS idx_failed_messages_group_id ON failed_messages(group_id);
CREATE INDEX IF NOT EXISTS idx_failed_messages_telegram_msg_id ON failed_messages(telegram_message_id);

-- Standalone index on messages.group_id (for queries including deleted messages)
CREATE INDEX IF NOT EXISTS idx_messages_group_id ON messages(group_id);

-- ============================================================
-- Revoked JWT Tokens (for token blacklisting on logout/refresh)
-- ============================================================
CREATE TABLE IF NOT EXISTS revoked_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    jti TEXT UNIQUE NOT NULL,
    user_id TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- idx_revoked_tokens_jti REMOVED — redundant with the UNIQUE constraint on jti,
-- which already creates an implicit unique index.
CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expires_at ON revoked_tokens(expires_at);

-- ============================================================
-- Functions and Triggers
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_telethon_sessions_updated_at BEFORE UPDATE ON telethon_sessions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_groups_updated_at BEFORE UPDATE ON groups
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_crawler_status_updated_at BEFORE UPDATE ON crawler_status
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_entity_cache_updated_at BEFORE UPDATE ON entity_cache
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Message Retention Cleanup Function (14-day policy)
-- ============================================================
-- Cleanup is handled by the FastAPI backend (main.py cleanup_old_messages task).
-- The pg_cron schedule below is optional redundancy if pg_cron is available:
--   SELECT cron.schedule('cleanup-old-messages', '0 * * * *',
--     $$SELECT cleanup_old_messages()$$);

CREATE OR REPLACE FUNCTION cleanup_old_messages()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER := 0;
    batch_deleted INTEGER;
BEGIN
    LOOP
        DELETE FROM messages
        WHERE id IN (
            SELECT id FROM messages
            WHERE sent_at < NOW() - INTERVAL '14 days'
            LIMIT 5000
        );
        GET DIAGNOSTICS batch_deleted = ROW_COUNT;
        deleted_count := deleted_count + batch_deleted;
        EXIT WHEN batch_deleted = 0;
        PERFORM pg_sleep(0.1);  -- yield between batches to reduce lock contention
    END LOOP;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Cleanup expired revoked tokens (called from app or pg_cron)
CREATE OR REPLACE FUNCTION cleanup_expired_revoked_tokens()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM revoked_tokens WHERE expires_at < NOW();
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- Row Level Security (RLS)
-- ============================================================
-- AaltoHub uses custom JWT auth (not Supabase Auth), so auth.uid() is not available.
-- The backend uses SUPABASE_SERVICE_ROLE_KEY which bypasses RLS entirely.
-- The frontend uses SUPABASE_ANON_KEY only for Realtime Broadcast subscriptions.
-- Therefore: block ALL direct table access for the anon role.
-- The service role (backend) is unaffected by these policies.

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE telethon_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE crawler_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE crawler_error_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE private_group_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE failed_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE revoked_tokens ENABLE ROW LEVEL SECURITY;

-- Deny all direct access for anon role.
-- No SELECT/INSERT/UPDATE/DELETE policies for anon = all queries return empty / are denied.
-- Service role bypasses RLS, so the backend is unaffected.

-- Public groups are readable by anon for potential future direct-query use.
-- For now, this is intentionally restrictive — all data flows through the backend API.

-- ============================================================
-- Realtime Publications
-- ============================================================
-- Messages use Supabase Broadcast API (pushed from backend), NOT Postgres Changes,
-- to avoid single-thread WAL replication bottleneck.
-- crawler_status is NOT published — the admin UI polls on a 30s interval,
-- and Postgres Changes WAL traffic adds cost with no benefit.
-- If you previously added crawler_status, remove it:
--   ALTER PUBLICATION supabase_realtime DROP TABLE IF EXISTS crawler_status;
