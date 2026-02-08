-- Rollback Migration 002: Revert Email-Only Signup Changes
-- WARNING: This will fail if there are email-only users (telegram_id IS NULL)

-- Remove identity constraint
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_must_have_identity;

-- Drop partial unique index
DROP INDEX IF EXISTS users_telegram_id_key;

-- Restore original unique constraint (this will fail if NULL values exist)
ALTER TABLE users ADD CONSTRAINT users_telegram_id_key UNIQUE (telegram_id);

-- Make telegram_id NOT NULL again (this will fail if NULL values exist)
ALTER TABLE users ALTER COLUMN telegram_id SET NOT NULL;

-- Rollback complete
SELECT 'Rollback 002 complete. Telegram ID is now required again.' AS status;
