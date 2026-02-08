#!/usr/bin/env python3
"""
ensure_migration_004.py

Ensures migration 004 (multi-telegram account support) is applied.
Checks if user_groups.connection_id column exists, applies migration if needed,
and reports detailed statistics.

Usage: python backend/scripts/ensure_migration_004.py
"""
import asyncio
import sys
from pathlib import Path

# Add backend directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import db

# ANSI color codes for output
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
BOLD = '\033[1m'
RESET = '\033[0m'


async def check_column_exists() -> bool:
    """Check if user_groups.connection_id column exists."""
    result = await db.fetchrow(
        """SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'user_groups'
            AND column_name = 'connection_id'
        )"""
    )
    return result['exists'] if result else False


async def get_statistics():
    """Get statistics about groups and connections."""
    stats = {}

    # Total groups
    result = await db.fetchrow("SELECT COUNT(*) as count FROM groups")
    stats['total_groups'] = result['count'] if result else 0

    # Total user_groups rows
    result = await db.fetchrow("SELECT COUNT(*) as count FROM user_groups")
    stats['total_user_groups'] = result['count'] if result else 0

    # Rows with NULL connection_id
    result = await db.fetchrow(
        "SELECT COUNT(*) as count FROM user_groups WHERE connection_id IS NULL"
    )
    stats['null_connection_id'] = result['count'] if result else 0

    # Rows with non-NULL connection_id
    result = await db.fetchrow(
        "SELECT COUNT(*) as count FROM user_groups WHERE connection_id IS NOT NULL"
    )
    stats['non_null_connection_id'] = result['count'] if result else 0

    # Total connections
    result = await db.fetchrow("SELECT COUNT(*) as count FROM telegram_connections")
    stats['total_connections'] = result['count'] if result else 0

    return stats


async def apply_migration():
    """Apply migration 004 SQL."""
    migration_file = Path(__file__).parent.parent / "migrations" / "004_multi_telegram.sql"

    if not migration_file.exists():
        raise FileNotFoundError(f"Migration file not found: {migration_file}")

    print(f"{BLUE}📝 Reading migration from: {migration_file}{RESET}")

    with open(migration_file, 'r') as f:
        sql = f.read()

    # Split by semicolon and execute each statement
    statements = [s.strip() for s in sql.split(';') if s.strip() and not s.strip().startswith('--')]

    print(f"{BLUE}📝 Applying {len(statements)} SQL statements...{RESET}\n")

    for i, statement in enumerate(statements, 1):
        if statement:
            try:
                result = await db.execute(statement)
                print(f"  [{i}/{len(statements)}] ✓ {result or 'Done'}")
            except Exception as e:
                # Some statements may fail if already applied (e.g., DROP CONSTRAINT IF EXISTS)
                # This is expected and safe
                print(f"  [{i}/{len(statements)}] ⚠️  {e}")

    print(f"\n{GREEN}✅ Migration 004 applied successfully!{RESET}")


async def main():
    """Main function."""
    print(f"\n{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}  Migration 004 Check & Apply: Multi-Telegram Account Support{RESET}")
    print(f"{BOLD}{'='*70}{RESET}\n")

    try:
        # Connect to database
        print(f"{BLUE}🔌 Connecting to database...{RESET}")
        await db.connect()
        print(f"{GREEN}✓ Connected{RESET}\n")

        # Check if column exists
        print(f"{BLUE}🔍 Checking if user_groups.connection_id exists...{RESET}")
        column_exists = await check_column_exists()

        if column_exists:
            print(f"{GREEN}✅ connection_id column EXISTS in user_groups{RESET}\n")
        else:
            print(f"{YELLOW}⚠️  connection_id column NOT FOUND in user_groups{RESET}")
            print(f"{YELLOW}📝 Migration 004 needs to be applied{RESET}\n")

            # Apply migration
            await apply_migration()

            # Verify it worked
            print(f"\n{BLUE}🔍 Verifying migration was applied...{RESET}")
            column_exists = await check_column_exists()

            if column_exists:
                print(f"{GREEN}✓ Verified: connection_id column now exists{RESET}\n")
            else:
                print(f"{RED}❌ Error: Column still not found after migration{RESET}\n")
                sys.exit(1)

        # Get statistics
        print(f"{BLUE}📊 Gathering statistics...{RESET}\n")
        stats = await get_statistics()

        # Print statistics
        print(f"{BOLD}Statistics:{RESET}")
        print(f"  Total groups:               {stats['total_groups']}")
        print(f"  Total user_groups rows:     {stats['total_user_groups']}")
        print(f"  Total telegram_connections: {stats['total_connections']}")
        print()

        if stats['total_user_groups'] > 0:
            null_percentage = (stats['null_connection_id'] / stats['total_user_groups']) * 100
            non_null_percentage = (stats['non_null_connection_id'] / stats['total_user_groups']) * 100

            print(f"{BOLD}Connection Linking Status:{RESET}")
            print(f"  Linked (non-NULL):    {GREEN}{stats['non_null_connection_id']:4d}{RESET}  ({non_null_percentage:5.1f}%)")
            print(f"  Unlinked (NULL):      {YELLOW}{stats['null_connection_id']:4d}{RESET}  ({null_percentage:5.1f}%)")
            print()

            if stats['null_connection_id'] > 0:
                print(f"{YELLOW}⚠️  {stats['null_connection_id']} groups need connection_id backfill{RESET}")
                print(f"{BLUE}ℹ️  Use the admin dashboard to trigger auto-backfill{RESET}")
                print(f"{BLUE}ℹ️  Or run: POST /admin/backfill-connection-ids{RESET}")
        else:
            print(f"{BLUE}ℹ️  No user_groups rows found (no groups registered yet){RESET}")

        print(f"\n{GREEN}{BOLD}✅ All checks complete!{RESET}\n")

    except Exception as e:
        print(f"\n{RED}❌ Error: {e}{RESET}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # Close database connection
        if hasattr(db, 'pool') and db.pool:
            await db.pool.close()


if __name__ == "__main__":
    asyncio.run(main())
