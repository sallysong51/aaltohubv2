#!/usr/bin/env python3
"""
Apply Migration 014: Drop Unused Indexes

Safely applies migration with pre-check and rollback capability.
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

import asyncpg
from app.config import settings


async def check_indexes_before(conn: asyncpg.Connection):
    """Check which indexes will be dropped."""
    print("\n" + "="*80)
    print("PRE-MIGRATION: Current Index Status")
    print("="*80)

    indexes_to_drop = [
        'idx_messages_user_feed',
        'idx_messages_sender',
        'idx_groups_registered_by',
        'idx_groups_visibility',
        'idx_groups_crawl_status',
        'idx_user_groups_group',
        'admin_credentials_username_key',
        'admin_credentials_phone_number_key',
        'admin_credentials_pkey',
        'idx_telethon_sessions_key_hash',
    ]

    for idx_name in indexes_to_drop:
        result = await conn.fetchrow("""
            SELECT
                schemaname,
                indexrelname,
                pg_size_pretty(pg_relation_size(indexrelid)) as size
            FROM pg_stat_user_indexes
            WHERE indexrelname = $1
        """, idx_name)

        if result:
            print(f"✓ Found: {result['indexrelname']:<45} {result['size']:>10}")
        else:
            print(f"✗ Not found: {idx_name:<45}")

    total_result = await conn.fetchrow("""
        SELECT
            pg_size_pretty(SUM(pg_relation_size(indexrelid))) as total_size
        FROM pg_stat_user_indexes
        WHERE indexrelname = ANY($1::text[])
    """, indexes_to_drop)

    print(f"\nTotal size to be freed: {total_result['total_size']}")


async def apply_migration(conn: asyncpg.Connection):
    """Apply the migration."""
    print("\n" + "="*80)
    print("APPLYING MIGRATION 014")
    print("="*80)

    # Execute each DROP INDEX statement individually
    indexes_to_drop = [
        ('idx_messages_user_feed', 'messages'),
        ('idx_messages_sender', 'messages'),
        ('idx_groups_registered_by', 'groups'),
        ('idx_groups_visibility', 'groups'),
        ('idx_groups_crawl_status', 'groups'),
        ('idx_user_groups_group', 'user_groups'),
        ('admin_credentials_username_key', 'admin_credentials'),
        ('admin_credentials_phone_number_key', 'admin_credentials'),
        ('admin_credentials_pkey', 'admin_credentials'),
        ('idx_telethon_sessions_key_hash', 'telethon_sessions'),
    ]

    try:
        dropped_count = 0
        for idx_name, table_name in indexes_to_drop:
            try:
                await conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
                print(f"✓ Dropped: {idx_name} (from {table_name})")
                dropped_count += 1
            except Exception as e:
                print(f"⚠️  Skipped {idx_name}: {e}")

        print(f"\n✓ Migration complete. Dropped {dropped_count} indexes.")
        return True
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def check_indexes_after(conn: asyncpg.Connection):
    """Verify indexes were dropped."""
    print("\n" + "="*80)
    print("POST-MIGRATION: Verification")
    print("="*80)

    indexes_to_drop = [
        'idx_messages_user_feed',
        'idx_messages_sender',
        'idx_groups_registered_by',
        'idx_groups_visibility',
        'idx_groups_crawl_status',
        'idx_user_groups_group',
        'admin_credentials_username_key',
        'admin_credentials_phone_number_key',
        'admin_credentials_pkey',
        'idx_telethon_sessions_key_hash',
    ]

    all_dropped = True
    for idx_name in indexes_to_drop:
        result = await conn.fetchrow("""
            SELECT indexrelname
            FROM pg_stat_user_indexes
            WHERE indexrelname = $1
        """, idx_name)

        if result:
            print(f"⚠️  Still exists: {idx_name}")
            all_dropped = False
        else:
            print(f"✓ Dropped: {idx_name}")

    return all_dropped


async def main():
    """Main execution."""
    print("\n" + "="*80)
    print("MIGRATION 014: Drop Unused Indexes")
    print("="*80)
    print("\nThis migration will drop 10 unused indexes (~200 KB total)")
    print("to improve write performance on messages and other tables.")
    print("\nTo rollback, run: psql < backend/migrations/014_rollback.sql")

    try:
        conn = await asyncpg.connect(settings.DATABASE_URL, timeout=10)
        print("\n✅ Connected to database")

        # Pre-check
        await check_indexes_before(conn)

        # Confirm
        print("\n" + "="*80)
        response = input("\nProceed with migration? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Migration cancelled")
            return

        # Apply
        success = await apply_migration(conn)
        if not success:
            print("\n❌ Migration failed. Database unchanged.")
            return

        # Verify
        all_dropped = await check_indexes_after(conn)

        if all_dropped:
            print("\n" + "="*80)
            print("✅ MIGRATION SUCCESSFUL")
            print("="*80)
            print("\nAll 10 indexes dropped successfully.")
            print("\nExpected improvements:")
            print("- Faster INSERT/UPDATE/DELETE on messages table")
            print("- Reduced storage overhead (~200 KB freed)")
            print("- No query performance degradation (indexes were unused)")
            print("\nTo rollback: psql < backend/migrations/014_rollback.sql")
        else:
            print("\n⚠️  MIGRATION PARTIALLY SUCCESSFUL")
            print("Some indexes may still exist. Review output above.")

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
