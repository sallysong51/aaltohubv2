-- Migration 008: Crawler Event Logging System
-- Purpose: Track all significant crawler events for operational visibility
-- 백엔드에서 무슨 일이 일어났는지, 언제, 어떻게 해결했는지 전체 상황 파악

-- ============================================================================
-- 1. crawler_events table — Comprehensive event log
-- ============================================================================
CREATE TABLE IF NOT EXISTS crawler_events (
    id BIGSERIAL PRIMARY KEY,

    -- Event classification
    event_type TEXT NOT NULL, -- 'error', 'info', 'warning', 'success', 'recovery'
    event_category TEXT NOT NULL, -- 'connection', 'crawl', 'database', 'media', 'gap_fill', 'circuit_breaker'

    -- Event content
    title TEXT NOT NULL, -- Short summary (e.g., "DB connection recovered")
    message TEXT NOT NULL, -- Detailed description

    -- Context
    group_id BIGINT REFERENCES groups(id) ON DELETE CASCADE, -- NULL for system-wide events
    connection_id TEXT, -- Telegram connection ID (for multi-admin tracking)

    -- Technical details
    details JSONB, -- Stack traces, retry counts, metrics, etc.

    -- Resolution tracking
    resolved BOOLEAN DEFAULT FALSE, -- Whether issue was auto-resolved
    resolved_at TIMESTAMPTZ, -- When it was resolved
    resolution_message TEXT, -- How it was resolved

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Indexing
    CONSTRAINT valid_event_type CHECK (event_type IN ('error', 'info', 'warning', 'success', 'recovery')),
    CONSTRAINT valid_event_category CHECK (event_category IN ('connection', 'crawl', 'database', 'media', 'gap_fill', 'circuit_breaker', 'system', 'auth', 'rate_limit'))
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_crawler_events_created_at ON crawler_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_crawler_events_type ON crawler_events(event_type) WHERE event_type IN ('error', 'warning');
CREATE INDEX IF NOT EXISTS idx_crawler_events_category ON crawler_events(event_category);
CREATE INDEX IF NOT EXISTS idx_crawler_events_group ON crawler_events(group_id) WHERE group_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_crawler_events_unresolved ON crawler_events(resolved, created_at DESC) WHERE resolved = FALSE;

-- Table description
COMMENT ON TABLE crawler_events IS 'Comprehensive crawler event log for operational visibility and debugging';
COMMENT ON COLUMN crawler_events.event_type IS 'Severity: error, warning, info, success, recovery';
COMMENT ON COLUMN crawler_events.event_category IS 'Category: connection, crawl, database, media, gap_fill, circuit_breaker, system, auth, rate_limit';
COMMENT ON COLUMN crawler_events.title IS 'Short event summary for quick scanning';
COMMENT ON COLUMN crawler_events.message IS 'Detailed description of what happened';
COMMENT ON COLUMN crawler_events.details IS 'Technical details: stack traces, retry counts, metrics (JSON)';
COMMENT ON COLUMN crawler_events.resolved IS 'Whether the issue was automatically resolved';
COMMENT ON COLUMN crawler_events.resolution_message IS 'How the issue was resolved (e.g., "DB connection recovered after 3 retries")';

-- ============================================================================
-- 2. crawler_metrics table — Time-series metrics for trends
-- ============================================================================
CREATE TABLE IF NOT EXISTS crawler_metrics (
    id BIGSERIAL PRIMARY KEY,

    -- Metric identification
    metric_name TEXT NOT NULL, -- 'messages_received', 'db_writes', 'media_downloads', etc.
    metric_value NUMERIC NOT NULL,

    -- Context
    group_id BIGINT REFERENCES groups(id) ON DELETE CASCADE,
    connection_id TEXT,

    -- Metadata
    timestamp TIMESTAMPTZ DEFAULT NOW(),

    -- Labels for filtering (e.g., {"status": "success", "source": "realtime"})
    labels JSONB DEFAULT '{}'::jsonb
);

-- Indexes for time-series queries
CREATE INDEX IF NOT EXISTS idx_crawler_metrics_timestamp ON crawler_metrics(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_crawler_metrics_name ON crawler_metrics(metric_name, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_crawler_metrics_group ON crawler_metrics(group_id, timestamp DESC) WHERE group_id IS NOT NULL;

COMMENT ON TABLE crawler_metrics IS 'Time-series metrics for trend analysis and monitoring';
COMMENT ON COLUMN crawler_metrics.metric_name IS 'Metric identifier (e.g., messages_received, db_writes_failed)';
COMMENT ON COLUMN crawler_metrics.labels IS 'Additional context as key-value pairs (JSON)';

-- ============================================================================
-- 3. Helper function: Record crawler event
-- ============================================================================
CREATE OR REPLACE FUNCTION record_crawler_event(
    p_event_type TEXT,
    p_event_category TEXT,
    p_title TEXT,
    p_message TEXT,
    p_group_id BIGINT DEFAULT NULL,
    p_connection_id TEXT DEFAULT NULL,
    p_details JSONB DEFAULT NULL
) RETURNS BIGINT AS $$
DECLARE
    v_event_id BIGINT;
BEGIN
    INSERT INTO crawler_events (event_type, event_category, title, message, group_id, connection_id, details)
    VALUES (p_event_type, p_event_category, p_title, p_message, p_group_id, p_connection_id, p_details)
    RETURNING id INTO v_event_id;

    RETURN v_event_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION record_crawler_event IS 'Helper function to insert crawler events with validation';

-- ============================================================================
-- 4. Auto-cleanup old events (retention: 30 days for info/success, 90 days for errors)
-- ============================================================================
CREATE OR REPLACE FUNCTION cleanup_old_crawler_events() RETURNS void AS $$
BEGIN
    -- Delete old info/success events (30 days)
    DELETE FROM crawler_events
    WHERE event_type IN ('info', 'success')
      AND created_at < NOW() - INTERVAL '30 days';

    -- Delete old error/warning events (90 days)
    DELETE FROM crawler_events
    WHERE event_type IN ('error', 'warning')
      AND created_at < NOW() - INTERVAL '90 days';

    -- Delete old metrics (7 days)
    DELETE FROM crawler_metrics
    WHERE timestamp < NOW() - INTERVAL '7 days';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_old_crawler_events IS 'Auto-cleanup: 30 days for info/success, 90 days for errors, 7 days for metrics';

-- You can schedule this with pg_cron or cron:
-- SELECT cron.schedule('cleanup-crawler-events', '0 2 * * *', 'SELECT cleanup_old_crawler_events()');
