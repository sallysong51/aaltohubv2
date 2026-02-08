-- Migration 001: Add Supabase Auth Integration
-- This migration adds columns and tables to support Supabase Auth (email/password)
-- while maintaining backward compatibility with existing Telegram auth.
--
-- Run this on an existing database to add Supabase Auth support.
-- This is an ADDITIVE migration — no data is deleted.

-- Add auth_user_id column to users table (links to auth.users.id)
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL;

-- Add email linking migration flags
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_link_required BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_linked_at TIMESTAMPTZ;

-- Create index for auth_user_id lookups
CREATE INDEX IF NOT EXISTS idx_users_auth_user_id ON users(auth_user_id) WHERE auth_user_id IS NOT NULL;

-- Create telegram_connections table (new home for Telegram sessions)
CREATE TABLE IF NOT EXISTS telegram_connections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    auth_user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    telegram_user_id BIGINT NOT NULL,
    phone_masked TEXT,
    username TEXT,
    session_encrypted TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    connected_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(auth_user_id, telegram_user_id),
    UNIQUE(telegram_user_id)
);

CREATE INDEX IF NOT EXISTS idx_telegram_connections_user_id ON telegram_connections(user_id);
CREATE INDEX IF NOT EXISTS idx_telegram_connections_auth_user_id ON telegram_connections(auth_user_id);
CREATE INDEX IF NOT EXISTS idx_telegram_connections_telegram_user_id ON telegram_connections(telegram_user_id);

-- Enable RLS
ALTER TABLE telegram_connections ENABLE ROW LEVEL SECURITY;

-- Create trigger for updated_at
CREATE TRIGGER update_telegram_connections_updated_at BEFORE UPDATE ON telegram_connections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Create email_linking_attempts table (rate limiting)
CREATE TABLE IF NOT EXISTS email_linking_attempts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    verification_token TEXT,
    expires_at TIMESTAMPTZ,
    attempt_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_linking_attempts_user_id ON email_linking_attempts(user_id);
CREATE INDEX IF NOT EXISTS idx_email_linking_attempts_expires_at ON email_linking_attempts(expires_at);

-- Enable RLS
ALTER TABLE email_linking_attempts ENABLE ROW LEVEL SECURITY;

-- Create trigger for updated_at
CREATE TRIGGER update_email_linking_attempts_updated_at BEFORE UPDATE ON email_linking_attempts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Mark existing users for email linking (they'll be prompted on next login)
-- This is safe to run multiple times (UPDATE with WHERE condition)
UPDATE users SET email_link_required = TRUE WHERE auth_user_id IS NULL;

-- Migration complete
SELECT 'Migration 001 complete. Added Supabase Auth support.' AS status;
