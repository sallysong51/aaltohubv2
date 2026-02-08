-- Rollback 004: Multi-Telegram Account Support
ALTER TABLE telegram_connections ALTER COLUMN auth_user_id SET NOT NULL;
ALTER TABLE telegram_connections ADD CONSTRAINT telegram_connections_telegram_user_id_key UNIQUE (telegram_user_id);
ALTER TABLE user_groups DROP COLUMN IF EXISTS connection_id;
