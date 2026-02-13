-- Rollback for Migration 014: Recreate dropped indexes
-- Use this if index removal causes performance issues

-- 1. idx_messages_user_feed (Phase 27)
CREATE INDEX IF NOT EXISTS idx_messages_user_feed
ON messages(group_id, message_source, sent_at DESC)
WHERE is_deleted = FALSE AND message_source = 'realtime';

-- 2. idx_messages_sender
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender_id);

-- 3-5. Group metadata indexes
CREATE INDEX IF NOT EXISTS idx_groups_registered_by ON groups(registered_by);
CREATE INDEX IF NOT EXISTS idx_groups_visibility ON groups(visibility);
CREATE INDEX IF NOT EXISTS idx_groups_crawl_status ON groups(crawl_status);

-- 6. idx_user_groups_group
CREATE INDEX IF NOT EXISTS idx_user_groups_group ON user_groups(group_id);

-- 7-9. admin_credentials indexes
-- Note: Primary key is already recreated by table definition
CREATE UNIQUE INDEX IF NOT EXISTS admin_credentials_username_key ON admin_credentials(username);
CREATE UNIQUE INDEX IF NOT EXISTS admin_credentials_phone_number_key ON admin_credentials(phone_number);
-- admin_credentials_pkey is handled by PRIMARY KEY constraint

-- 10. idx_telethon_sessions_key_hash
CREATE INDEX IF NOT EXISTS idx_telethon_sessions_key_hash ON telethon_sessions(key_hash);

SELECT 'Rollback 008 complete. Recreated all dropped indexes.' AS status;
