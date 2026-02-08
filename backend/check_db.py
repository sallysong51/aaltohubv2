#!/usr/bin/env python3
"""Quick DB diagnostic script"""
import asyncio
import asyncpg
from datetime import datetime, timedelta

DATABASE_URL = "postgresql://postgres.ejbozuggauzivpznzngu:HJYPsOKrEyNGEcwR@aws-1-eu-central-1.pooler.supabase.com:5432/postgres"

async def check_db():
    conn = await asyncpg.connect(DATABASE_URL)

    print("=" * 60)
    print("📊 DATABASE DIAGNOSTIC REPORT")
    print("=" * 60)

    # 1. Total messages
    total = await conn.fetchval("SELECT COUNT(*) FROM messages")
    print(f"\n✅ Total messages in DB: {total:,}")

    # 2. Messages by source
    sources = await conn.fetch("""
        SELECT message_source, COUNT(*) as count
        FROM messages
        GROUP BY message_source
        ORDER BY count DESC
    """)
    print(f"\n📦 Messages by source:")
    for row in sources:
        print(f"   - {row['message_source']}: {row['count']:,}")

    # 3. Get all groups info
    all_groups = await conn.fetch("SELECT * FROM groups LIMIT 1")
    if all_groups:
        print(f"\n📁 Groups table columns: {list(all_groups[0].keys())}")

    # 3b. Messages by group (using correct column name)
    groups_query = """
        SELECT COUNT(*) as total_groups,
               COUNT(*) FILTER (WHERE crawl_enabled = true) as crawl_enabled_count
        FROM groups
    """
    group_stats = await conn.fetchrow(groups_query)
    print(f"\n📁 Groups:")
    print(f"   Total groups: {group_stats['total_groups']}")
    print(f"   Crawl enabled: {group_stats['crawl_enabled_count']}")

    # 4. Check for NULL created_at
    null_created = await conn.fetchval("SELECT COUNT(*) FROM messages WHERE created_at IS NULL")
    print(f"\n⚠️  Messages with NULL created_at: {null_created:,}")

    # 5. Date range
    date_range = await conn.fetchrow("""
        SELECT
            MIN(sent_at) as earliest,
            MAX(sent_at) as latest
        FROM messages
    """)
    if date_range['earliest']:
        print(f"\n📅 Message date range:")
        print(f"   Earliest: {date_range['earliest']}")
        print(f"   Latest: {date_range['latest']}")

    # 6. Recent messages (last 14 days)
    two_weeks_ago = datetime.now() - timedelta(days=14)
    recent_count = await conn.fetchval(
        "SELECT COUNT(*) FROM messages WHERE sent_at >= $1",
        two_weeks_ago
    )
    print(f"\n📆 Messages from last 14 days: {recent_count:,}")

    # 7. Crawler status check
    crawler_status = await conn.fetch("""
        SELECT g.name, cs.status, cs.progress, cs.estimated_total, cs.last_error, cs.updated_at
        FROM groups g
        LEFT JOIN crawler_status cs ON cs.group_telegram_id = g.id
        ORDER BY cs.updated_at DESC NULLS LAST
        LIMIT 10
    """)
    print(f"\n🤖 Crawler status (recent 10):")
    for row in crawler_status:
        status_str = row['status'] or 'never_crawled'
        progress_str = f"{row['progress'] or 0}/{row['estimated_total'] or '?'}" if row['status'] else "N/A"
        error_str = f" ERROR: {row['last_error'][:50]}" if row['last_error'] else ""
        print(f"   - {row['name'][:30]:30} | {status_str:12} | {progress_str:10}{error_str}")

    await conn.close()
    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(check_db())
