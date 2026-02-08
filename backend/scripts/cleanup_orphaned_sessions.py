#!/usr/bin/env python3
"""
Clean up orphaned telethon_sessions entries.

This script removes telethon_sessions entries that have been successfully
migrated to telegram_connections. Only run this AFTER confirming all users
can log in and their sessions are working correctly.

Usage:
    python backend/scripts/cleanup_orphaned_sessions.py

IMPORTANT: This is a DESTRUCTIVE operation. Make sure to:
1. Run verify_migration.py first to confirm migration is complete
2. Test that users can log in and crawling still works
3. Have a database backup before running this script

Safe to run multiple times (idempotent).
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import db
from app.session_migration import cleanup_orphaned_sessions


async def main():
    """Run orphaned session cleanup."""
    print("\n" + "=" * 60)
    print("  ORPHANED SESSION CLEANUP")
    print("=" * 60 + "\n")

    print("⚠️  WARNING: This will DELETE telethon_sessions entries that")
    print("   have been migrated to telegram_connections.")
    print()
    print("   Make sure you have:")
    print("   1. Run verify_migration.py (missing_tc = 0)")
    print("   2. Tested that users can log in")
    print("   3. Confirmed crawling still works")
    print("   4. Have a database backup")
    print()

    # Ask for confirmation
    try:
        response = input("Do you want to proceed? (yes/no): ").strip().lower()
        if response != "yes":
            print("\nAborted. No changes made.")
            return
    except (KeyboardInterrupt, EOFError):
        print("\n\nAborted. No changes made.")
        return

    print("\nStarting cleanup...")

    try:
        await db.connect()
        deleted = await cleanup_orphaned_sessions()

        print(f"\n✓ Cleanup complete: {deleted} orphaned sessions deleted")
        print()
        print("=" * 60)
        print("  CLEANUP COMPLETE")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
