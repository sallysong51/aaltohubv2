-- Rollback for Migration 003

-- Drop index
DROP INDEX IF EXISTS idx_messages_user_feed;

-- Remove column
ALTER TABLE messages DROP COLUMN IF EXISTS message_source;

SELECT 'Migration 003 rolled back.' AS status;
