-- Migration: Backfill NULL created_at values and add NOT NULL constraint
-- Purpose: Ensure all messages have valid created_at timestamps to prevent Pydantic validation errors
-- Related: AdminDashboard 500 error fix (Phase 29)

-- Step 1: Backfill NULL created_at values
-- Use sent_at if available, otherwise use NOW()
UPDATE messages
SET created_at = COALESCE(sent_at, NOW())
WHERE created_at IS NULL;

-- Step 2: Verify no NULL values remain
DO $$
DECLARE
    null_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO null_count FROM messages WHERE created_at IS NULL;
    IF null_count > 0 THEN
        RAISE EXCEPTION 'Migration failed: % rows still have NULL created_at', null_count;
    END IF;
    RAISE NOTICE 'Migration successful: All created_at values are non-NULL';
END $$;

-- Step 3: Add NOT NULL constraint to prevent future issues
ALTER TABLE messages
ALTER COLUMN created_at SET NOT NULL;

-- Verification query (run after migration)
-- SELECT COUNT(*) as total_messages,
--        COUNT(created_at) as non_null_created_at,
--        COUNT(*) FILTER (WHERE created_at IS NULL) as null_created_at
-- FROM messages;
-- Expected: null_created_at = 0
