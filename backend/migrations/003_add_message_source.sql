-- Migration 003: Add message_source column to messages table
-- This migration adds source tracking to distinguish crawled vs real-time messages.
-- Crawled messages will be hidden from user feeds but visible in admin dashboard.

-- Add message_source column with default 'realtime'
ALTER TABLE messages
ADD COLUMN IF NOT EXISTS message_source TEXT NOT NULL DEFAULT 'realtime' CHECK (message_source IN ('realtime', 'crawled', 'gap_fill'));

-- Create optimized index for user feed queries (realtime messages only)
CREATE INDEX IF NOT EXISTS idx_messages_user_feed
ON messages(group_id, message_source, sent_at DESC)
WHERE is_deleted = FALSE AND message_source = 'realtime';

SELECT 'Migration 003 complete. Added message_source column.' AS status;
