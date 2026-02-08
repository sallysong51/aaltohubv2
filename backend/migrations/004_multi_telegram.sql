-- Migration 004: Multi-Telegram Account Support
-- Allows one email user to link multiple Telegram accounts

-- 1. Make auth_user_id nullable (we use custom JWT, not Supabase Auth for all users)
ALTER TABLE telegram_connections ALTER COLUMN auth_user_id DROP NOT NULL;

-- 2. Drop global uniqueness on telegram_user_id
--    (same TG account can be linked by different users — e.g. admin copies)
--    Keep UNIQUE(user_id, telegram_user_id) to prevent duplicate links per user
ALTER TABLE telegram_connections DROP CONSTRAINT IF EXISTS telegram_connections_telegram_user_id_key;

-- 3. Add UNIQUE(user_id, telegram_user_id) for ON CONFLICT support
ALTER TABLE telegram_connections
    ADD CONSTRAINT telegram_connections_user_id_telegram_user_id_key
    UNIQUE (user_id, telegram_user_id);

-- 4. Add connection_id to user_groups to track which TG connection registered each group
ALTER TABLE user_groups ADD COLUMN IF NOT EXISTS connection_id UUID REFERENCES telegram_connections(id) ON DELETE SET NULL;
