-- Entity cache: stores (channel_id, access_hash) pairs to avoid
-- repeated get_entity() / get_dialogs() Telegram API calls that cause FloodWaitError.

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TABLE IF NOT EXISTS entity_cache (
    telegram_id BIGINT PRIMARY KEY,
    access_hash BIGINT NOT NULL DEFAULT 0,
    entity_type TEXT NOT NULL DEFAULT 'channel' CHECK (entity_type IN ('channel', 'chat')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER update_entity_cache_updated_at BEFORE UPDATE ON entity_cache
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
