#!/usr/bin/env python3
"""Add test events to crawler_events table for UI testing"""
import asyncio
import asyncpg
import json
from pathlib import Path
from datetime import datetime, timedelta

async def main():
    # Read DATABASE_URL from .env
    env_file = Path(__file__).parent.parent / ".env"
    database_url = None

    with open(env_file) as f:
        for line in f:
            if line.startswith("DATABASE_URL="):
                database_url = line.split("=", 1)[1].strip()
                break

    if not database_url:
        print("❌ DATABASE_URL not found in .env")
        return

    try:
        conn = await asyncpg.connect(database_url)
        print("✅ Connected to database")

        # Get a sample group_id if exists
        group_row = await conn.fetchrow("SELECT id FROM groups LIMIT 1")
        sample_group_id = group_row['id'] if group_row else None

        # Insert test events
        test_events = [
            {
                "event_type": "success",
                "event_category": "system",
                "title": "크롤러 시작됨",
                "message": "라이브 크롤러가 정상적으로 시작되었습니다",
                "group_id": None,
                "details": {"version": "2.0", "environment": "development"},
                "created_at": datetime.now() - timedelta(minutes=30),
            },
            {
                "event_type": "info",
                "event_category": "crawl",
                "title": "역사 크롤링 시작",
                "message": "14일 치 메시지 수집을 시작합니다",
                "group_id": sample_group_id,
                "details": {"days": 14},
                "created_at": datetime.now() - timedelta(minutes=25),
            },
            {
                "event_type": "success",
                "event_category": "crawl",
                "title": "역사 크롤링 완료",
                "message": "1,234개의 메시지를 성공적으로 수집했습니다",
                "group_id": sample_group_id,
                "details": {"messages_collected": 1234, "duration_seconds": 45},
                "created_at": datetime.now() - timedelta(minutes=24),
            },
            {
                "event_type": "warning",
                "event_category": "media",
                "title": "미디어 다운로드 타임아웃",
                "message": "미디어 파일 다운로드가 30초 제한 시간을 초과했습니다",
                "group_id": sample_group_id,
                "details": {"file_size": 15728640, "timeout_seconds": 30},
                "resolved": False,
                "created_at": datetime.now() - timedelta(minutes=20),
            },
            {
                "event_type": "error",
                "event_category": "database",
                "title": "DB 쓰기 실패",
                "message": "데이터베이스 연결이 끊어져 메시지를 저장할 수 없습니다",
                "group_id": None,
                "details": {"error": "connection lost", "retry_count": 3},
                "resolved": False,
                "created_at": datetime.now() - timedelta(minutes=15),
            },
            {
                "event_type": "recovery",
                "event_category": "database",
                "title": "DB 연결 복구됨",
                "message": "데이터베이스 연결이 자동으로 복구되었습니다 (3회 재시도 후)",
                "group_id": None,
                "details": {"retry_count": 3, "downtime_seconds": 45},
                "resolved": True,
                "resolved_at": datetime.now() - timedelta(minutes=14),
                "resolution_message": "자동 재연결 성공 (3회 재시도)",
                "created_at": datetime.now() - timedelta(minutes=14),
            },
            {
                "event_type": "info",
                "event_category": "gap_fill",
                "title": "갭 필 시작",
                "message": "최근 3시간 메시지 누락 확인 중",
                "group_id": None,
                "details": {"lookback_hours": 3},
                "created_at": datetime.now() - timedelta(minutes=10),
            },
            {
                "event_type": "success",
                "event_category": "gap_fill",
                "title": "갭 필 완료",
                "message": "5개의 누락된 메시지를 복구했습니다",
                "group_id": None,
                "details": {"gaps_filled": 5},
                "created_at": datetime.now() - timedelta(minutes=9),
            },
        ]

        for event in test_events:
            await conn.execute(
                """
                INSERT INTO crawler_events
                (event_type, event_category, title, message, group_id, details, resolved, resolved_at, resolution_message, created_at)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10)
                """,
                event["event_type"],
                event["event_category"],
                event["title"],
                event["message"],
                event.get("group_id"),
                json.dumps(event.get("details")) if event.get("details") else None,
                event.get("resolved", False),
                event.get("resolved_at"),
                event.get("resolution_message"),
                event["created_at"],
            )

        print(f"✅ Added {len(test_events)} test events")

        # Verify
        count = await conn.fetchval("SELECT COUNT(*) FROM crawler_events")
        print(f"✅ Total events in table: {count}")

        await conn.close()
        print("🎉 Test events added successfully!")

    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
