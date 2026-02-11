-- Rollback for Migration 009: Message Metadata
-- Removes links, mentions, photo_count columns and their indexes

-- Drop indexes first (dependent objects)
DROP INDEX IF EXISTS idx_messages_photo_count;
DROP INDEX IF EXISTS idx_messages_mentions;
DROP INDEX IF EXISTS idx_messages_links;

-- Drop columns
ALTER TABLE messages DROP COLUMN IF EXISTS photo_count;
ALTER TABLE messages DROP COLUMN IF EXISTS mentions;
ALTER TABLE messages DROP COLUMN IF EXISTS links;
