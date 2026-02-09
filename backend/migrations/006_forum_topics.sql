-- Migration 006: Add forum topics support
-- Creates group_topics table to store real topic metadata from Telegram

CREATE TABLE IF NOT EXISTS group_topics (
    id BIGSERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL,  -- Telegram topic ID (message ID of root message)
    topic_title TEXT NOT NULL,
    icon_color INTEGER,
    icon_emoji_id BIGINT,
    is_closed BOOLEAN DEFAULT FALSE,
    is_pinned BOOLEAN DEFAULT FALSE,
    top_message_id INTEGER,
    unread_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(group_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_group_topics_group_id ON group_topics(group_id);
CREATE INDEX IF NOT EXISTS idx_group_topics_topic_id ON group_topics(group_id, topic_id);

-- Ensure has_topics column exists (should already be there from schema_actual.sql)
-- This is idempotent
ALTER TABLE groups
    ADD COLUMN IF NOT EXISTS has_topics BOOLEAN DEFAULT FALSE;
