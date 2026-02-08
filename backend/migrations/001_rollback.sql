-- Rollback Migration 001: Remove Supabase Auth Integration
-- This script reverses all changes made by 001_add_supabase_auth.sql
-- Use this if you need to roll back to Telegram-only auth.
--
-- WARNING: This will delete telegram_connections and email_linking_attempts tables
-- and all data within them. Make sure you have backups before running.

-- Drop new tables
DROP TABLE IF EXISTS email_linking_attempts CASCADE;
DROP TABLE IF EXISTS telegram_connections CASCADE;

-- Remove new columns from users table
ALTER TABLE users DROP COLUMN IF EXISTS auth_user_id;
ALTER TABLE users DROP COLUMN IF EXISTS email_link_required;
ALTER TABLE users DROP COLUMN IF EXISTS email_linked_at;

-- Drop index
DROP INDEX IF EXISTS idx_users_auth_user_id;

-- Rollback complete
SELECT 'Rollback 001 complete. Removed Supabase Auth support.' AS status;
