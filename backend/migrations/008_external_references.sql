-- Migration: External Reference Discovery & Auto-Crawling
-- System 2: Automated web scraping and Telegram group joining
-- Created: 2026-02-11
-- Rate limits: 3 joins/hour, 10 joins/day, 10 scrapes/hour

-- =============================================================================
-- TABLE 1: External References (Discovered URLs)
-- =============================================================================
CREATE TABLE external_references (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id BIGINT REFERENCES messages(id) ON DELETE CASCADE,
    reference_type TEXT NOT NULL CHECK (reference_type IN ('web_url', 'telegram_link')),
    url TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'scraped', 'joined', 'failed', 'blacklisted')),
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE INDEX idx_references_status ON external_references(status, discovered_at DESC);
CREATE INDEX idx_references_message ON external_references(message_id);
CREATE INDEX idx_references_type ON external_references(reference_type);

COMMENT ON TABLE external_references IS 'External URLs and Telegram links discovered in messages for crawling';
COMMENT ON COLUMN external_references.reference_type IS 'web_url=HTTP(S) link, telegram_link=t.me/* link';
COMMENT ON COLUMN external_references.status IS 'pending=not processed, scraped/joined=success, failed=error, blacklisted=blocked';

-- =============================================================================
-- TABLE 2: Scraping Queue (Web Scraping with Playwright)
-- =============================================================================
CREATE TABLE scraping_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reference_id UUID REFERENCES external_references(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    scraped_content JSONB,  -- {title, description, event_date, location, raw_html}
    scraped_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_scraping_status ON scraping_queue(status, created_at) WHERE status IN ('pending', 'failed');
CREATE INDEX idx_scraping_reference ON scraping_queue(reference_id);

COMMENT ON TABLE scraping_queue IS 'Queue for web scraping via Playwright MCP (rate limit: 10/hour)';
COMMENT ON COLUMN scraping_queue.scraped_content IS 'Extracted event details from scraped webpage';
COMMENT ON COLUMN scraping_queue.retry_count IS 'Number of retry attempts (max 3)';

-- =============================================================================
-- TABLE 3: Telegram Join Queue (Auto-Join Groups)
-- =============================================================================
CREATE TABLE telegram_join_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reference_id UUID REFERENCES external_references(id) ON DELETE CASCADE,
    telegram_link TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'joined', 'failed', 'rate_limited')),
    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    joined_group_id BIGINT REFERENCES groups(id),
    joined_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_join_status ON telegram_join_queue(status, created_at) WHERE status IN ('pending', 'failed', 'rate_limited');
CREATE INDEX idx_join_reference ON telegram_join_queue(reference_id);

COMMENT ON TABLE telegram_join_queue IS 'Queue for auto-joining referenced Telegram groups (rate limit: 3/hour, 10/day per connection)';
COMMENT ON COLUMN telegram_join_queue.status IS 'rate_limited=FloodWait penalty active';
COMMENT ON COLUMN telegram_join_queue.joined_group_id IS 'Foreign key to groups table after successful join';

-- =============================================================================
-- TABLE 4: Crawl Rate Limits (Per-Connection Tracking)
-- =============================================================================
CREATE TABLE crawl_rate_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID REFERENCES telegram_connections(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL CHECK (action_type IN ('join_group', 'web_scrape')),
    hourly_count INTEGER DEFAULT 0,
    daily_count INTEGER DEFAULT 0,
    last_reset_hour TIMESTAMPTZ DEFAULT NOW(),
    last_reset_day TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(connection_id, action_type)
);

CREATE INDEX idx_rate_limits_connection ON crawl_rate_limits(connection_id, action_type);

COMMENT ON TABLE crawl_rate_limits IS 'Per-connection rate limit tracking to prevent Telegram FloodWait penalties';
COMMENT ON COLUMN crawl_rate_limits.hourly_count IS 'Joins/scrapes in current hour (resets every hour)';
COMMENT ON COLUMN crawl_rate_limits.daily_count IS 'Joins/scrapes in current day (resets daily)';

-- =============================================================================
-- TABLE 5: Crawl Blacklist (Safety & Legal Compliance)
-- =============================================================================
CREATE TABLE crawl_blacklist (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern TEXT NOT NULL UNIQUE,
    reason TEXT NOT NULL,
    added_by BIGINT REFERENCES users(id),
    added_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_blacklist_pattern ON crawl_blacklist(pattern);

COMMENT ON TABLE crawl_blacklist IS 'URL/domain patterns to block from automatic crawling (e.g., illegal sites, spam domains)';
COMMENT ON COLUMN crawl_blacklist.pattern IS 'Regex or substring pattern to match against URLs (e.g., "scam.com", "illegal-site.*)';

-- =============================================================================
-- TABLE 6: Context Keywords (Group Context Extraction)
-- =============================================================================
CREATE TABLE context_keywords (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id BIGINT REFERENCES groups(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    frequency INTEGER DEFAULT 1,
    last_seen TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(group_id, keyword)
);

CREATE INDEX idx_context_group ON context_keywords(group_id);
CREATE INDEX idx_context_frequency ON context_keywords(frequency DESC);

COMMENT ON TABLE context_keywords IS 'Keyword frequency tracking for group context (updated with group_contexts every 6 hours)';
COMMENT ON COLUMN context_keywords.frequency IS 'Number of times this keyword appeared in last 30 days';

-- =============================================================================
-- SEED DATA: Initial Blacklist Entries
-- =============================================================================

-- Blacklist common spam/scam domains
INSERT INTO crawl_blacklist (pattern, reason)
VALUES
    ('bit.ly', 'URL shortener - often used for spam'),
    ('t.me/joinchat', 'Private group invites - requires manual approval'),
    ('scam', 'Keyword indicates potential scam'),
    ('betting', 'Gambling sites not relevant to student events'),
    ('casino', 'Gambling sites not relevant to student events')
ON CONFLICT (pattern) DO NOTHING;
