#!/usr/bin/env python3
"""Apply migration 008 - Crawler Event Logging System"""
import asyncio
import asyncpg
from pathlib import Path

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

    # Read migration file
    migration_file = Path(__file__).parent.parent / "migrations" / "008_crawler_events.sql"
    migration_sql = migration_file.read_text()

    print(f"📁 Migration file: {migration_file}")
    print(f"🔗 Database: {database_url.split('@')[1] if '@' in database_url else database_url}")

    # Apply migration
    try:
        conn = await asyncpg.connect(database_url)
        print("✅ Connected to database")

        await conn.execute(migration_sql)
        print("✅ Migration 008 applied successfully")

        # Verify tables created
        tables = await conn.fetch("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            AND tablename IN ('crawler_events', 'crawler_metrics')
            ORDER BY tablename
        """)

        print(f"✅ Created tables: {', '.join([t['tablename'] for t in tables])}")

        # Check indexes
        indexes = await conn.fetch("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'public'
            AND tablename IN ('crawler_events', 'crawler_metrics')
            ORDER BY indexname
        """)

        print(f"✅ Created indexes: {len(indexes)} indexes")

        await conn.close()
        print("🎉 Migration complete!")

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
