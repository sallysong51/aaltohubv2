-- ============================================================
-- crawler_status 테이블 생성 + Realtime 활성화
-- ============================================================

-- 1. crawler_status 테이블 생성
CREATE TABLE IF NOT EXISTS crawler_status (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id BIGINT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'inactive' CHECK (status IN ('active', 'inactive', 'error', 'initializing')),
    is_enabled BOOLEAN DEFAULT TRUE,
    last_message_at TIMESTAMPTZ,
    last_error TEXT,
    error_count INTEGER DEFAULT 0,
    initial_crawl_progress INTEGER DEFAULT 0,
    initial_crawl_total INTEGER DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(group_id)
);

CREATE INDEX IF NOT EXISTS idx_crawler_status_group_id ON crawler_status(group_id);

-- 2. crawler_status를 Realtime publication에 추가
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND tablename = 'crawler_status'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE crawler_status;
    END IF;
END $$;

-- 3. 기존 그룹 crawl_enabled 활성화
UPDATE groups SET crawl_enabled = true WHERE crawl_enabled = false;
