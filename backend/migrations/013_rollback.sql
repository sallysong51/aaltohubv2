-- Rollback Migration 013: Auto-Join Feature - Join Attempts Tracking Table

-- Drop indexes first (CASCADE not needed for indexes)
DROP INDEX IF EXISTS idx_join_attempts_group_id;
DROP INDEX IF EXISTS idx_join_attempts_cleanup;
DROP INDEX IF EXISTS idx_join_attempts_success_time;
DROP INDEX IF EXISTS idx_join_attempts_telegram_user_time;
DROP INDEX IF EXISTS idx_join_attempts_connection_time;

-- Drop table (CASCADE will drop any dependent objects)
DROP TABLE IF EXISTS join_attempts CASCADE;
