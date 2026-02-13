-- Migration 014: Drop unused indexes to improve write performance
-- Based on database diagnostics showing 10 unused indexes (idx_scan = 0)
--
-- Performance impact:
-- - Faster INSERT/UPDATE/DELETE operations (no index maintenance)
-- - Reduced storage overhead (~200 KB total)
-- - No query performance degradation (indexes were not being used)
--
-- Rollback: See 014_rollback.sql to recreate indexes if needed

-- 1. idx_messages_user_feed (32 kB) - Phase 27
-- REASON: PostgreSQL planner prefers idx_messages_group_id for small dataset
-- ANALYSIS: EXPLAIN ANALYZE showed all queries use idx_messages_group_id instead
-- DECISION: Drop. May revisit when messages table exceeds 10 GB.
DROP INDEX IF EXISTS idx_messages_user_feed;

-- 2. idx_messages_sender (16 kB)
-- REASON: No queries filter by sender_id alone (always joined with group_id)
-- DECISION: Drop. sender_id lookups already efficient via idx_messages_group_id.
DROP INDEX IF EXISTS idx_messages_sender;

-- 3-5. Group metadata indexes (48 kB total)
-- These indexes are rarely queried (admin operations only, not user-facing)
-- REASON: Low query frequency, small table size (80 kB)
DROP INDEX IF EXISTS idx_groups_registered_by;  -- Admin-only query
DROP INDEX IF EXISTS idx_groups_visibility;     -- Rarely filtered
DROP INDEX IF EXISTS idx_groups_crawl_status;   -- Admin-only query

-- 6. idx_user_groups_group (16 kB)
-- REASON: user_groups_user_id_group_id_key (unique constraint) already covers this
-- DECISION: Drop. Composite unique index handles both user_id and group_id lookups.
DROP INDEX IF EXISTS idx_user_groups_group;

-- 7-9. admin_credentials indexes (48 kB total) - SKIPPED
-- REASON: These are constraint-backed indexes (UNIQUE, PRIMARY KEY)
-- Cannot be dropped independently without dropping constraints
-- DECISION: Keep. They are required for data integrity.
-- Note: idx_scan = 0 because they're only used for constraint validation
-- DROP INDEX IF EXISTS admin_credentials_username_key;  -- UNIQUE constraint
-- DROP INDEX IF EXISTS admin_credentials_phone_number_key;  -- UNIQUE constraint
-- DROP INDEX IF EXISTS admin_credentials_pkey;  -- PRIMARY KEY constraint

-- 10. idx_telethon_sessions_key_hash (16 kB)
-- REASON: Sessions are always looked up by PK (id), not key_hash
-- DECISION: Drop. telethon_sessions_pkey is sufficient.
DROP INDEX IF EXISTS idx_telethon_sessions_key_hash;

-- Summary
SELECT 'Migration 014 complete. Dropped 7 unused indexes (~144 KB freed). Skipped 3 constraint-backed indexes.' AS status;

-- Notes for future:
-- 1. If messages table exceeds 10 GB, consider recreating idx_messages_user_feed
-- 2. Monitor query performance after migration
-- 3. Use EXPLAIN ANALYZE periodically to validate index usage
