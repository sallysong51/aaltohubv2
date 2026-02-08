-- Data Validation Queries for Messages Table
-- Purpose: Diagnose potential issues before/after migration
-- Run these queries to check data integrity

-- ============================================================
-- 1. Check for NULL values in required fields
-- ============================================================

-- NULL created_at (should be 0 after migration)
SELECT
    COUNT(*) as null_created_at_count,
    COUNT(*) * 100.0 / (SELECT COUNT(*) FROM messages) as percentage
FROM messages
WHERE created_at IS NULL;

-- NULL sent_at (should be 0)
SELECT
    COUNT(*) as null_sent_at_count,
    COUNT(*) * 100.0 / (SELECT COUNT(*) FROM messages) as percentage
FROM messages
WHERE sent_at IS NULL;

-- NULL telegram_message_id (critical - should be 0)
SELECT
    COUNT(*) as null_telegram_id_count
FROM messages
WHERE telegram_message_id IS NULL;

-- ============================================================
-- 2. Check message_source distribution
-- ============================================================

SELECT
    message_source,
    COUNT(*) as count,
    COUNT(*) * 100.0 / (SELECT COUNT(*) FROM messages) as percentage,
    MIN(created_at) as earliest,
    MAX(created_at) as latest
FROM messages
GROUP BY message_source
ORDER BY count DESC;

-- ============================================================
-- 3. Sample messages by source
-- ============================================================

-- Recent crawled messages
SELECT
    id,
    telegram_message_id,
    group_id,
    LEFT("text", 50) as text_preview,
    sent_at,
    created_at,
    message_source
FROM messages
WHERE message_source = 'crawled'
ORDER BY created_at DESC
LIMIT 10;

-- Recent realtime messages
SELECT
    id,
    telegram_message_id,
    group_id,
    LEFT("text", 50) as text_preview,
    sent_at,
    created_at,
    message_source
FROM messages
WHERE message_source = 'realtime'
ORDER BY created_at DESC
LIMIT 10;

-- ============================================================
-- 4. Check for potential problematic data
-- ============================================================

-- Messages where created_at > sent_at (unusual but possible)
SELECT
    COUNT(*) as future_created_count,
    AVG(EXTRACT(EPOCH FROM (created_at - sent_at))) as avg_diff_seconds
FROM messages
WHERE created_at > sent_at + INTERVAL '1 minute';

-- Messages with very old sent_at but recent created_at (backfilled)
SELECT
    COUNT(*) as likely_backfilled
FROM messages
WHERE sent_at < NOW() - INTERVAL '30 days'
  AND created_at > NOW() - INTERVAL '1 day';

-- ============================================================
-- 5. Group-level message counts
-- ============================================================

SELECT
    g.id as group_id,
    g.title,
    COUNT(m.id) as total_messages,
    COUNT(m.id) FILTER (WHERE m.message_source = 'crawled') as crawled_messages,
    COUNT(m.id) FILTER (WHERE m.message_source = 'realtime') as realtime_messages,
    COUNT(m.id) FILTER (WHERE m.message_source = 'gap_fill') as gap_fill_messages,
    MAX(m.created_at) as latest_message
FROM groups g
LEFT JOIN messages m ON m.group_id = g.id
GROUP BY g.id, g.title
ORDER BY total_messages DESC
LIMIT 20;

-- ============================================================
-- 6. Identify specific problematic rows (if any)
-- ============================================================

-- Rows that would fail Pydantic validation
SELECT
    id,
    telegram_message_id,
    group_id,
    sent_at,
    created_at,
    message_source,
    CASE
        WHEN telegram_message_id IS NULL THEN 'Missing telegram_message_id'
        WHEN group_id IS NULL THEN 'Missing group_id'
        WHEN sent_at IS NULL THEN 'Missing sent_at'
        WHEN created_at IS NULL THEN 'Missing created_at'
        ELSE 'Unknown issue'
    END as issue
FROM messages
WHERE telegram_message_id IS NULL
   OR group_id IS NULL
   OR sent_at IS NULL
   OR created_at IS NULL
LIMIT 50;
