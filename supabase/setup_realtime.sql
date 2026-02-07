-- ============================================================
-- AaltoHub v2: Realtime 설정 + crawler_status 테이블 생성
-- Supabase SQL Editor에서 실행하세요
-- ============================================================

-- 1. crawler_status 테이블 생성
CREATE TABLE IF NOT EXISTS crawler_status (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
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

-- 2. Realtime 활성화
DO $$
BEGIN
    -- messages 테이블 Realtime 추가
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND tablename = 'messages'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE messages;
        RAISE NOTICE 'Added messages to supabase_realtime';
    ELSE
        RAISE NOTICE 'messages already in supabase_realtime';
    END IF;

    -- crawler_status 테이블 Realtime 추가
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND tablename = 'crawler_status'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE crawler_status;
        RAISE NOTICE 'Added crawler_status to supabase_realtime';
    ELSE
        RAISE NOTICE 'crawler_status already in supabase_realtime';
    END IF;
END $$;

-- 3. 기존 그룹에 crawl_enabled 활성화
UPDATE groups SET crawl_enabled = true WHERE crawl_enabled = false;

-- 4. 확인
SELECT 'Realtime tables:' AS info;
SELECT tablename FROM pg_publication_tables WHERE pubname = 'supabase_realtime';

SELECT 'Groups with crawl_enabled:' AS info;
SELECT id, name, crawl_enabled FROM groups;

SELECT 'crawler_status rows:' AS info;
SELECT * FROM crawler_status;
