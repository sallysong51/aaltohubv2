-- Migration 002: Enable Email-Only Signup
-- Makes telegram_id nullable to support users who sign up with email only (no Telegram account)

-- Make telegram_id nullable
ALTER TABLE users ALTER COLUMN telegram_id DROP NOT NULL;

-- Update unique constraint to allow NULL telegram_id (multiple NULL values allowed)
-- Drop existing unique constraint
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_telegram_id_key;

-- Create partial unique index (only enforces uniqueness for non-NULL values)
CREATE UNIQUE INDEX IF NOT EXISTS users_telegram_id_key ON users(telegram_id) WHERE telegram_id IS NOT NULL;

-- Add constraint: user must have either telegram_id OR auth_user_id (at least one)
ALTER TABLE users ADD CONSTRAINT users_must_have_identity
    CHECK (telegram_id IS NOT NULL OR auth_user_id IS NOT NULL);

-- Migration complete
SELECT 'Migration 002 complete. Users can now sign up with email only.' AS status;
