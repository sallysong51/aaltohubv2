-- Migration 009: Add message metadata columns
-- Purpose: Store structured link/mention data and photo album counts
-- Author: Phase 34 - Message Metadata Enhancement
-- Date: 2026-02-11

-- Add new columns for structured metadata
ALTER TABLE messages ADD COLUMN links JSONB DEFAULT NULL;
ALTER TABLE messages ADD COLUMN mentions JSONB DEFAULT NULL;
ALTER TABLE messages ADD COLUMN photo_count INTEGER DEFAULT NULL;

-- Add GIN indexes for JSONB query performance
-- Conditional indexes: only non-NULL values indexed (most messages don't have these)
CREATE INDEX idx_messages_links ON messages USING GIN (links)
  WHERE links IS NOT NULL;

CREATE INDEX idx_messages_mentions ON messages USING GIN (mentions)
  WHERE mentions IS NOT NULL;

CREATE INDEX idx_messages_photo_count ON messages (photo_count)
  WHERE photo_count > 1;

-- Documentation for future developers
COMMENT ON COLUMN messages.links IS
  'Array of link objects extracted from message.entities: [{"url": "https://...", "text": "optional display text"}]. NULL if no links.';

COMMENT ON COLUMN messages.mentions IS
  'Array of mention objects extracted from message.entities: [{"username": "@channel", "id": 123}]. NULL if no mentions.';

COMMENT ON COLUMN messages.photo_count IS
  'Number of photos in photo album. NULL for single photo or no photos, 2+ for albums. Simplified: exact count requires tracking grouped_id across messages.';
