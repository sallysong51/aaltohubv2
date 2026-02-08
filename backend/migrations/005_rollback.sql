-- Rollback for 005_backfill_timestamps.sql
-- Removes the NOT NULL constraint (does not revert backfilled data)

ALTER TABLE messages
ALTER COLUMN created_at DROP NOT NULL;

-- Note: Backfilled created_at values are NOT reverted
-- If you need to identify backfilled rows, check where created_at = sent_at
