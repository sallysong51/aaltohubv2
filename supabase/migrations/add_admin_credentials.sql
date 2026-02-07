-- Create admin_credentials table for multi-admin support
-- Allows storing multiple phone numbers and usernames that have admin access

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

-- Indexes for fast lookup during login
CREATE INDEX IF NOT EXISTS idx_admin_credentials_phone ON admin_credentials(phone_number) WHERE phone_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_admin_credentials_username ON admin_credentials(username) WHERE username IS NOT NULL;

-- Enable RLS (Row Level Security)
ALTER TABLE admin_credentials ENABLE ROW LEVEL SECURITY;

-- Policy: Everyone can read (needed for auth checks)
CREATE POLICY "admin_credentials_readable" ON admin_credentials
    FOR SELECT TO authenticated USING (true);

-- Policy: Only admins can insert/delete
CREATE POLICY "admin_credentials_admin_only" ON admin_credentials
    FOR INSERT TO authenticated WITH CHECK (
        EXISTS(SELECT 1 FROM users WHERE id = auth.uid() AND role = 'admin')
    );

CREATE POLICY "admin_credentials_admin_delete" ON admin_credentials
    FOR DELETE TO authenticated USING (
        EXISTS(SELECT 1 FROM users WHERE id = auth.uid() AND role = 'admin')
    );

-- Seed with initial admin credentials (one-time setup)
-- These should be updated with your actual admin phone/username
INSERT INTO admin_credentials (phone_number, username) VALUES
    ('+821076207783', 'test'),
    ('+358449598622', '@chaeyeonsally')
ON CONFLICT DO NOTHING;
