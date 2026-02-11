-- Rollback Migration 008: Crawler Event Logging System

DROP FUNCTION IF EXISTS cleanup_old_crawler_events() CASCADE;
DROP FUNCTION IF EXISTS record_crawler_event(TEXT, TEXT, TEXT, TEXT, BIGINT, TEXT, JSONB) CASCADE;
DROP TABLE IF EXISTS crawler_metrics CASCADE;
DROP TABLE IF EXISTS crawler_events CASCADE;
