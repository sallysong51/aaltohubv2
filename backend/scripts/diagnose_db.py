#!/usr/bin/env python3
"""
Database Diagnostics Script
Performs comprehensive health checks on Supabase PostgreSQL database.

Usage:
    python backend/scripts/diagnose_db.py

Checks:
1. Connection pooler configuration
2. Active connections count
3. Long-running queries
4. Index usage statistics
5. Table sizes (especially messages table)
6. Connection age distribution
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

import asyncpg
from app.config import settings


async def check_pooler_config(conn: asyncpg.Connection):
    """Check connection pooler settings."""
    print("\n" + "="*80)
    print("1. CONNECTION POOLER CONFIGURATION")
    print("="*80)

    # Check max connections
    result = await conn.fetchrow("SHOW max_connections;")
    print(f"Max connections: {result['max_connections']}")

    # Check pooler mode (from connection string)
    db_url = settings.DATABASE_URL
    if ':5432/' in db_url:
        if 'pooler.supabase.com' in db_url:
            print("Pooler mode: Session pooler (✅ Good for LISTEN/NOTIFY)")
        else:
            print("Pooler mode: Direct connection (✅ Good for development)")
    elif ':6543/' in db_url:
        print("⚠️  WARNING: Transaction pooler (port 6543) breaks LISTEN/NOTIFY!")
        print("   Change to Session pooler (port 5432) immediately!")

    # Check current connection count vs max
    active = await conn.fetchrow("""
        SELECT count(*) as active_connections
        FROM pg_stat_activity
        WHERE state != 'idle';
    """)
    print(f"Active connections: {active['active_connections']}")

    # Connection limit utilization
    max_conn = int(result['max_connections'])
    active_count = int(active['active_connections'])
    utilization = (active_count / max_conn) * 100
    print(f"Connection utilization: {utilization:.1f}%")

    if utilization > 80:
        print("⚠️  WARNING: High connection utilization (>80%)")
    elif utilization > 50:
        print("ℹ️  NOTICE: Moderate connection utilization (>50%)")


async def check_active_connections(conn: asyncpg.Connection):
    """Check active connections by application and state."""
    print("\n" + "="*80)
    print("2. ACTIVE CONNECTIONS BREAKDOWN")
    print("="*80)

    # By application name
    apps = await conn.fetch("""
        SELECT
            application_name,
            state,
            count(*) as conn_count,
            max(now() - backend_start) as max_age
        FROM pg_stat_activity
        WHERE pid != pg_backend_pid()
        GROUP BY application_name, state
        ORDER BY conn_count DESC
        LIMIT 10;
    """)

    print("\nBy application:")
    print(f"{'Application':<30} {'State':<15} {'Count':>8} {'Max Age':<20}")
    print("-" * 80)
    for row in apps:
        app_name = row['application_name'] or '(unknown)'
        state = row['state'] or 'unknown'
        count = row['conn_count']
        max_age = str(row['max_age']).split('.')[0] if row['max_age'] else '0:00:00'
        print(f"{app_name:<30} {state:<15} {count:>8} {max_age:<20}")

    # Idle connections
    idle_count = await conn.fetchrow("""
        SELECT count(*) as idle_connections
        FROM pg_stat_activity
        WHERE state = 'idle'
        AND now() - state_change > interval '5 minutes';
    """)

    print(f"\nIdle connections (>5 min): {idle_count['idle_connections']}")
    if idle_count['idle_connections'] > 10:
        print("ℹ️  Consider reducing max_inactive_connection_lifetime in pool config")


async def check_long_running_queries(conn: asyncpg.Connection):
    """Check for long-running queries."""
    print("\n" + "="*80)
    print("3. LONG-RUNNING QUERIES")
    print("="*80)

    queries = await conn.fetch("""
        SELECT
            pid,
            now() - query_start as duration,
            state,
            left(query, 100) as query_preview
        FROM pg_stat_activity
        WHERE state != 'idle'
        AND now() - query_start > interval '10 seconds'
        ORDER BY duration DESC
        LIMIT 10;
    """)

    if not queries:
        print("✅ No long-running queries (>10 seconds)")
        return

    print(f"\n{'PID':<10} {'Duration':<15} {'State':<15} {'Query Preview':<60}")
    print("-" * 100)
    for row in queries:
        duration = str(row['duration']).split('.')[0]
        query = row['query_preview'].replace('\n', ' ').strip()
        print(f"{row['pid']:<10} {duration:<15} {row['state']:<15} {query:<60}")

    print(f"\n⚠️  Found {len(queries)} long-running queries")


async def check_index_usage(conn: asyncpg.Connection):
    """Check index usage statistics."""
    print("\n" + "="*80)
    print("4. INDEX USAGE STATISTICS")
    print("="*80)

    # Unused indexes
    unused = await conn.fetch("""
        SELECT
            schemaname,
            relname as tablename,
            indexrelname as indexname,
            idx_scan,
            pg_size_pretty(pg_relation_size(indexrelid)) as index_size
        FROM pg_stat_user_indexes
        WHERE idx_scan = 0
        AND schemaname = 'public'
        ORDER BY pg_relation_size(indexrelid) DESC
        LIMIT 10;
    """)

    if unused:
        print("\nUnused indexes (never scanned):")
        print(f"{'Table':<30} {'Index':<40} {'Size':<15} {'Scans':>10}")
        print("-" * 100)
        for row in unused:
            print(f"{row['tablename']:<30} {row['indexname']:<40} {row['index_size']:<15} {row['idx_scan']:>10}")
        print(f"\nℹ️  {len(unused)} unused indexes found - consider dropping if confirmed unused")
    else:
        print("✅ All indexes are being used")

    # Most used indexes
    print("\n\nMost used indexes:")
    most_used = await conn.fetch("""
        SELECT
            relname as tablename,
            indexrelname as indexname,
            idx_scan,
            idx_tup_read,
            idx_tup_fetch
        FROM pg_stat_user_indexes
        WHERE schemaname = 'public'
        ORDER BY idx_scan DESC
        LIMIT 10;
    """)

    print(f"{'Table':<30} {'Index':<40} {'Scans':>12} {'Tuples Read':>15}")
    print("-" * 100)
    for row in most_used:
        print(f"{row['tablename']:<30} {row['indexname']:<40} {row['idx_scan']:>12} {row['idx_tup_read']:>15}")


async def check_table_sizes(conn: asyncpg.Connection):
    """Check table sizes, especially messages table."""
    print("\n" + "="*80)
    print("5. TABLE SIZES")
    print("="*80)

    tables = await conn.fetch("""
        SELECT
            schemaname,
            tablename,
            pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size,
            pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) as table_size,
            pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename)) as indexes_size,
            pg_total_relation_size(schemaname||'.'||tablename) as total_bytes
        FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY total_bytes DESC
        LIMIT 15;
    """)

    print(f"\n{'Table':<30} {'Total Size':<15} {'Table':<15} {'Indexes':<15}")
    print("-" * 80)
    for row in tables:
        print(f"{row['tablename']:<30} {row['total_size']:<15} {row['table_size']:<15} {row['indexes_size']:<15}")

    # Messages table specific analysis
    messages_row = next((r for r in tables if r['tablename'] == 'messages'), None)
    if messages_row:
        print("\n\nMessages table analysis:")

        # Row count
        count = await conn.fetchrow("SELECT count(*) as total FROM messages;")
        print(f"Total messages: {count['total']:,}")

        # Deleted messages
        deleted = await conn.fetchrow("SELECT count(*) as deleted FROM messages WHERE is_deleted = TRUE;")
        deleted_pct = (deleted['deleted'] / count['total'] * 100) if count['total'] > 0 else 0
        print(f"Deleted messages: {deleted['deleted']:,} ({deleted_pct:.1f}%)")

        # Oldest message
        oldest = await conn.fetchrow("SELECT min(sent_at) as oldest FROM messages;")
        print(f"Oldest message: {oldest['oldest']}")

        # Recommendations
        total_gb = messages_row['total_bytes'] / (1024**3)
        if total_gb > 10:
            print("\n⚠️  RECOMMENDATION: Messages table is large (>10 GB)")
            print("   Consider implementing partitioning for better query performance")

        if deleted_pct > 10:
            print(f"\nℹ️  NOTICE: {deleted_pct:.1f}% of messages are soft-deleted")
            print("   Consider implementing auto-cleanup for old deleted messages")


async def check_connection_age_distribution(conn: asyncpg.Connection):
    """Check connection age distribution (Phase 33 validation)."""
    print("\n" + "="*80)
    print("6. CONNECTION AGE DISTRIBUTION (Phase 33 Validation)")
    print("="*80)

    ages = await conn.fetch("""
        WITH age_data AS (
            SELECT
                CASE
                    WHEN now() - backend_start < interval '1 minute' THEN '<1 min'
                    WHEN now() - backend_start < interval '5 minutes' THEN '1-5 min'
                    WHEN now() - backend_start < interval '10 minutes' THEN '5-10 min'
                    WHEN now() - backend_start < interval '30 minutes' THEN '10-30 min'
                    ELSE '>30 min'
                END as age_bucket,
                CASE
                    WHEN now() - backend_start < interval '1 minute' THEN 1
                    WHEN now() - backend_start < interval '5 minutes' THEN 2
                    WHEN now() - backend_start < interval '10 minutes' THEN 3
                    WHEN now() - backend_start < interval '30 minutes' THEN 4
                    ELSE 5
                END as bucket_order
            FROM pg_stat_activity
            WHERE pid != pg_backend_pid()
        )
        SELECT age_bucket, count(*) as conn_count
        FROM age_data
        GROUP BY age_bucket, bucket_order
        ORDER BY bucket_order;
    """)

    print(f"\n{'Age Bucket':<15} {'Connection Count':>20}")
    print("-" * 40)
    total = 0
    for row in ages:
        print(f"{row['age_bucket']:<15} {row['conn_count']:>20}")
        total += row['conn_count']
    print("-" * 40)
    print(f"{'Total':<15} {total:>20}")

    # Check if max_inactive_connection_lifetime is working (should see turnover)
    old_connections = next((r['conn_count'] for r in ages if r['age_bucket'] == '>30 min'), 0)
    if old_connections > total * 0.5:
        print("\n⚠️  WARNING: >50% of connections are older than 30 minutes")
        print("   Phase 33's max_inactive_connection_lifetime (5 min) may not be working")
        print("   Check if connections are actually idle or actively used")


async def main():
    """Run all diagnostics."""
    print("\n" + "="*80)
    print("SUPABASE DATABASE DIAGNOSTICS")
    print("="*80)
    print(f"\nConnecting to database...")

    try:
        conn = await asyncpg.connect(settings.DATABASE_URL, timeout=10)
        print("✅ Connected successfully\n")

        # Run all checks
        await check_pooler_config(conn)
        await check_active_connections(conn)
        await check_long_running_queries(conn)
        await check_index_usage(conn)
        await check_table_sizes(conn)
        await check_connection_age_distribution(conn)

        print("\n" + "="*80)
        print("DIAGNOSTICS COMPLETE")
        print("="*80)
        print("\nNext steps:")
        print("1. Review warnings and recommendations above")
        print("2. If messages table is large, consider partitioning (see docs)")
        print("3. If deleted messages are >10%, consider auto-cleanup")
        print("4. Monitor connection age distribution to validate Phase 33")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    finally:
        if 'conn' in locals():
            await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
