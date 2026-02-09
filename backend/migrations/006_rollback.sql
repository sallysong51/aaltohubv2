-- Rollback for Migration 006: Forum Topics Support

DROP TABLE IF EXISTS group_topics CASCADE;

-- Do NOT drop has_topics column (already exists in production schema and may be used elsewhere)
