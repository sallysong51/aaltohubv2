-- Migration: AI Classification & Prompt Management
-- System 1: AI-powered message classification with cost optimization
-- Created: 2026-02-11
-- Estimated cost: $4.70/month with 3-layer optimization

-- =============================================================================
-- TABLE 1: Prompts (Versioning & Management)
-- =============================================================================
CREATE TABLE prompts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('classification', 'extraction', 'hidden_cost')),
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    is_active BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by BIGINT REFERENCES users(id),
    UNIQUE(name, version)
);

CREATE INDEX idx_prompts_active ON prompts(type, is_active) WHERE is_active = true;

COMMENT ON TABLE prompts IS 'AI prompt versioning for classification, extraction, and hidden cost detection';
COMMENT ON COLUMN prompts.type IS 'classification=categorize message, extraction=extract event data, hidden_cost=detect membership fees';
COMMENT ON COLUMN prompts.is_active IS 'Only one prompt per type can be active at a time';

-- =============================================================================
-- TABLE 2: Classification History (Audit Trail)
-- =============================================================================
CREATE TABLE classification_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id BIGINT REFERENCES messages(id) ON DELETE CASCADE,
    prompt_version_id UUID REFERENCES prompts(id),
    ai_category TEXT NOT NULL,
    ai_confidence NUMERIC(3,2) CHECK (ai_confidence BETWEEN 0 AND 1),
    raw_response JSONB,
    processing_time_ms INTEGER,
    cost_tokens INTEGER,
    classified_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_classification_message ON classification_history(message_id);
CREATE INDEX idx_classification_prompt ON classification_history(prompt_version_id);
CREATE INDEX idx_classification_date ON classification_history(classified_at DESC);

COMMENT ON TABLE classification_history IS 'Complete audit trail of all AI classifications for debugging and A/B testing';
COMMENT ON COLUMN classification_history.raw_response IS 'Full JSON response from Claude API for debugging';
COMMENT ON COLUMN classification_history.cost_tokens IS 'Token count for cost tracking (0 if cached)';

-- =============================================================================
-- TABLE 3: Group Contexts (Context-Aware Classification)
-- =============================================================================
CREATE TABLE group_contexts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id BIGINT REFERENCES groups(id) ON DELETE CASCADE,
    keywords JSONB,  -- {sport: 12, competition: 8, free: 5}
    activity_patterns JSONB,  -- {peak_hours: [18, 19, 20], daily_avg: 45.2}
    top_senders JSONB,  -- [{user_id: 123, msg_count: 45, username: "admin"}]
    membership_info JSONB,  -- {detected: true, type: "paid", amount: 40, period: "year"}
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(group_id)
);

CREATE INDEX idx_group_contexts_updated ON group_contexts(last_updated DESC);

COMMENT ON TABLE group_contexts IS 'Aggregated group metadata for context-aware AI classification (updated every 6 hours)';
COMMENT ON COLUMN group_contexts.keywords IS 'Top 50 keywords from last 30 days with frequency counts';
COMMENT ON COLUMN group_contexts.membership_info IS 'Detected membership requirements from message patterns';

-- =============================================================================
-- TABLE 4: Classification Statistics (Monitoring)
-- =============================================================================
CREATE TABLE classification_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    prompt_version_id UUID REFERENCES prompts(id),
    messages_processed INTEGER DEFAULT 0,
    total_cost_usd NUMERIC(10,4) DEFAULT 0,
    avg_confidence NUMERIC(3,2),
    category_breakdown JSONB,  -- {event: 120, info: 45, chat: 230, spam: 5}
    UNIQUE(date, prompt_version_id)
);

CREATE INDEX idx_classification_stats_date ON classification_stats(date DESC);

COMMENT ON TABLE classification_stats IS 'Daily aggregated statistics for cost tracking and performance monitoring';
COMMENT ON COLUMN classification_stats.total_cost_usd IS 'Daily cost calculated from token counts (input + output)';

-- =============================================================================
-- TABLE 5: Classification Queue (Async Processing)
-- =============================================================================
CREATE TABLE classification_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id BIGINT REFERENCES messages(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE INDEX idx_queue_status ON classification_queue(status, created_at) WHERE status IN ('pending', 'failed');

COMMENT ON TABLE classification_queue IS 'Async message classification queue with retry logic';
COMMENT ON COLUMN classification_queue.retry_count IS 'Number of retry attempts (max 3)';

-- =============================================================================
-- TABLE 6: Event Metadata (Extracted Structured Data)
-- =============================================================================
CREATE TABLE event_metadata (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id BIGINT REFERENCES messages(id) ON DELETE CASCADE,
    event_date TIMESTAMPTZ,
    event_location TEXT,
    event_fee NUMERIC(10,2),
    event_currency TEXT DEFAULT 'EUR',
    registration_url TEXT,
    registration_deadline TIMESTAMPTZ,
    capacity INTEGER,
    hidden_costs JSONB,  -- [{type: "membership", amount: 40, description: "Annual fee required"}]
    extracted_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(message_id)
);

CREATE INDEX idx_event_metadata_date ON event_metadata(event_date) WHERE event_date IS NOT NULL;

COMMENT ON TABLE event_metadata IS 'AI-extracted structured event information from classified event messages';
COMMENT ON COLUMN event_metadata.hidden_costs IS 'Array of hidden cost requirements detected by AI (membership fees, etc)';

-- =============================================================================
-- TABLE 7: AI Batches (Batch Processing Tracking)
-- =============================================================================
CREATE TABLE ai_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_size INTEGER NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    total_tokens INTEGER,
    total_cost_usd NUMERIC(10,4),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ai_batches_status ON ai_batches(status, created_at DESC);

COMMENT ON TABLE ai_batches IS 'Tracking for AI batch API calls (5 messages per batch for cost optimization)';
COMMENT ON COLUMN ai_batches.batch_size IS 'Number of messages in this batch (target: 5)';

-- =============================================================================
-- TABLE 8: AI Cache (30-day LRU)
-- =============================================================================
CREATE TABLE ai_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_hash TEXT NOT NULL UNIQUE,
    prompt_version_id UUID REFERENCES prompts(id),
    response JSONB NOT NULL,
    hit_count INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cache_accessed ON ai_cache(last_accessed_at DESC);
CREATE INDEX idx_cache_hash ON ai_cache(message_hash);

COMMENT ON TABLE ai_cache IS '30-day LRU cache for AI responses (expected 20% hit rate, saves $0.94/month)';
COMMENT ON COLUMN ai_cache.message_hash IS 'SHA256(message_text + prompt_version) for cache key';
COMMENT ON COLUMN ai_cache.hit_count IS 'Number of cache hits (for metrics)';

-- =============================================================================
-- ALTER EXISTING TABLE: messages
-- =============================================================================
ALTER TABLE messages
ADD COLUMN ai_category TEXT,
ADD COLUMN ai_confidence NUMERIC(3,2) CHECK (ai_confidence BETWEEN 0 AND 1),
ADD COLUMN ai_classified_at TIMESTAMPTZ,
ADD COLUMN prompt_version_id UUID REFERENCES prompts(id);

CREATE INDEX idx_messages_ai_category ON messages(ai_category) WHERE ai_category IS NOT NULL;

COMMENT ON COLUMN messages.ai_category IS 'AI classification result: event, info, chat, or spam';
COMMENT ON COLUMN messages.ai_confidence IS 'AI confidence score 0.0-1.0 (higher = more confident)';

-- =============================================================================
-- SEED DATA: Initial Prompts
-- =============================================================================

-- Classification Prompt (v1)
INSERT INTO prompts (name, type, version, content, is_active)
VALUES (
    'message_classification',
    'classification',
    1,
    'You are an AI assistant that classifies Telegram messages for a student event platform.

Classify each message into ONE of these categories:
- **event**: Announcements of upcoming events (sports, competitions, workshops, parties, etc)
- **info**: General information, updates, or announcements (not events)
- **chat**: Casual conversation, greetings, questions, off-topic discussion
- **spam**: Advertisements, spam, irrelevant content

For each message, respond with:
{
  "category": "event|info|chat|spam",
  "confidence": 0.0-1.0
}

Examples:
- "Football match this Saturday at 15:00 in Otaniemi" → event (0.95)
- "Registration for hackathon closes tomorrow" → event (0.90)
- "Reminder: library hours changed" → info (0.85)
- "Hey, anyone going to the party?" → chat (0.90)
- "Buy cheap textbooks here: ..." → spam (0.95)',
    true
);

-- Event Extraction Prompt (v1)
INSERT INTO prompts (name, type, version, content, is_active)
VALUES (
    'event_extraction',
    'extraction',
    1,
    'You are an AI assistant that extracts structured event information from Telegram messages.

Extract the following fields if mentioned:
- **event_date**: ISO 8601 format (e.g., "2026-03-15T15:00:00Z")
- **event_location**: Physical location or venue name
- **event_fee**: Numeric amount (e.g., 5.0)
- **event_currency**: Currency code (e.g., "EUR", "USD")
- **registration_url**: URL for registration/tickets
- **registration_deadline**: ISO 8601 format
- **capacity**: Maximum number of participants

Respond with JSON:
{
  "event_date": "...",
  "event_location": "...",
  "event_fee": 5.0,
  "event_currency": "EUR",
  "registration_url": "...",
  "registration_deadline": "...",
  "capacity": 50
}

Only include fields that are explicitly mentioned. Return null for missing fields.',
    true
);

-- Hidden Cost Detection Prompt (v1)
INSERT INTO prompts (name, type, version, content, is_active)
VALUES (
    'hidden_cost_detection',
    'hidden_cost',
    1,
    'You are an AI assistant that detects hidden costs or membership requirements in event messages.

Common hidden costs:
- Membership fees (annual, monthly)
- Required purchases (equipment, uniforms)
- Deposit requirements
- Club/organization membership required

Analyze the message and detect ANY costs or requirements that are NOT explicitly stated as the event fee.

Respond with JSON array:
[
  {
    "type": "membership|deposit|equipment|other",
    "amount": 40.0,
    "currency": "EUR",
    "description": "Annual club membership required"
  }
]

Return empty array [] if no hidden costs detected.

Important: Look for contextual clues like "for members", "club fee", "annual subscription", etc.',
    true
);
