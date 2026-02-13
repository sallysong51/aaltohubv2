#!/usr/bin/env python3
"""
Analyze idx_messages_user_feed usage with EXPLAIN ANALYZE.

Tests whether the user feed query uses the idx_messages_user_feed index.
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

import asyncpg
from app.config import settings


async def analyze_query(conn: asyncpg.Connection, query: str, params: list, label: str):
    """Run EXPLAIN ANALYZE on a query and print the plan."""
    print(f"\n{'='*80}")
    print(f"{label}")
    print(f"{'='*80}\n")

    # First show the query
    print("Query:")
    print(query)
    print(f"\nParams: {params}\n")

    # Run EXPLAIN ANALYZE
    explain_query = f"EXPLAIN (ANALYZE, BUFFERS, VERBOSE) {query}"
    try:
        result = await conn.fetch(explain_query, *params)
        print("Execution plan:")
        print("-" * 80)
        for row in result:
            print(row[0])
        print("-" * 80)

        # Check if index is used
        plan_text = "\n".join([row[0] for row in result])
        if "idx_messages_user_feed" in plan_text:
            print("\n✅ Index idx_messages_user_feed IS USED")
        else:
            print("\n❌ Index idx_messages_user_feed IS NOT USED")

        # Check for sequential scan
        if "Seq Scan on messages" in plan_text:
            print("⚠️  WARNING: Using sequential scan instead of index")

    except Exception as e:
        print(f"❌ Error: {e}")


async def main():
    """Test different query patterns."""
    print("\n" + "="*80)
    print("USER FEED INDEX ANALYSIS")
    print("="*80)
    print("\nAnalyzing idx_messages_user_feed usage in different query patterns")
    print("Index definition:")
    print("  ON messages(group_id, message_source, sent_at DESC)")
    print("  WHERE is_deleted = FALSE AND message_source = 'realtime'")

    try:
        conn = await asyncpg.connect(settings.DATABASE_URL, timeout=10)
        print("\n✅ Connected to database")

        # Test 1: Ideal query (should use index)
        query1 = """
            SELECT id, group_id, "text", sender_id, sent_at
            FROM messages
            WHERE group_id = $1
              AND is_deleted = FALSE
              AND message_source = 'realtime'
            ORDER BY sent_at DESC
            LIMIT 50
        """
        await analyze_query(
            conn, query1, [1],
            "TEST 1: User feed query (ideal - matches index exactly)"
        )

        # Test 2: Missing message_source filter
        query2 = """
            SELECT id, group_id, "text", sender_id, sent_at
            FROM messages
            WHERE group_id = $1
              AND is_deleted = FALSE
            ORDER BY sent_at DESC
            LIMIT 50
        """
        await analyze_query(
            conn, query2, [1],
            "TEST 2: Missing message_source filter (should NOT use idx_messages_user_feed)"
        )

        # Test 3: Multiple groups (IN clause)
        query3 = """
            SELECT id, group_id, "text", sender_id, sent_at
            FROM messages
            WHERE group_id = ANY($1::bigint[])
              AND is_deleted = FALSE
              AND message_source = 'realtime'
            ORDER BY sent_at DESC
            LIMIT 50
        """
        await analyze_query(
            conn, query3, [[1, 2, 3]],
            "TEST 3: Multiple groups with IN clause (aggregated feed)"
        )

        # Test 4: Without is_deleted filter
        query4 = """
            SELECT id, group_id, "text", sender_id, sent_at
            FROM messages
            WHERE group_id = $1
              AND message_source = 'realtime'
            ORDER BY sent_at DESC
            LIMIT 50
        """
        await analyze_query(
            conn, query4, [1],
            "TEST 4: Without is_deleted filter (should NOT use partial index)"
        )

        # Test 5: Check existing query pattern (find actual queries)
        print("\n" + "="*80)
        print("RECOMMENDATIONS")
        print("="*80)
        print("""
1. If TEST 1 uses the index: User feed queries MUST include:
   - WHERE group_id = ?
   - AND is_deleted = FALSE
   - AND message_source = 'realtime'
   - ORDER BY sent_at DESC

2. If TEST 1 does NOT use the index:
   - Index may be redundant (too small dataset for planner to use it)
   - Or index definition doesn't match query pattern
   - Consider dropping if dataset grows and still not used

3. If TEST 2/3/4 show better performance:
   - Current index definition may be wrong
   - Adjust index to match actual query patterns

4. Current index size: 32 kB (from diagnostics)
   - Very small, indicates low selectivity or small dataset
   - May not be worth the write overhead until dataset grows

Next steps:
- Review app/routes/*.py for actual messages SELECT queries
- Update queries to match index definition (include all filters)
- Or update index to match actual query patterns
- Or drop index if confirmed unused after query review
        """)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if 'conn' in locals():
            await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
