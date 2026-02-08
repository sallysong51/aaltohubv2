#!/usr/bin/env python3
"""
Verify session migration integrity.

This script checks that all users who have linked their email (auth_user_id)
also have their Telegram sessions migrated to the telegram_connections table.

Usage:
    python backend/scripts/verify_migration.py

Safe to run at any time (read-only).
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import db
from app.session_migration import verify_migration_integrity


async def main():
    """Run migration verification."""
    print("\n" + "=" * 60)
    print("  SESSION MIGRATION VERIFICATION")
    print("=" * 60 + "\n")

    try:
        await db.connect()
        results = await verify_migration_integrity()

        # Display results
        print(f"Total linked users (auth_user_id set): {results['total_linked_users']}")
        print(f"Users with telegram_connections:       {results['users_with_tc']}")
        print(f"Users missing telegram_connections:    {results['missing_tc']}")
        print(f"Orphaned telethon_sessions (cleanup):  {results['orphaned_sessions']}")

        # Show details of missing users
        if results['missing_tc'] > 0:
            print("\n⚠️  USERS MISSING TELEGRAM_CONNECTIONS:")
            print("-" * 60)
            for user in results['missing_tc_details']:
                print(f"  ID: {user['id']}, Telegram ID: {user['telegram_id']}, "
                      f"Username: {user.get('username') or 'N/A'}, "
                      f"Phone: {user.get('phone_number') or 'N/A'}")
            print()
            print("ACTION: Run migration again or manually investigate these users.")
        else:
            print("\n✓ All users have successfully migrated sessions!")

        # Cleanup recommendation
        if results['orphaned_sessions'] > 0:
            print(f"\n💡 INFO: {results['orphaned_sessions']} sessions in telethon_sessions")
            print("   can be cleaned up (already exist in telegram_connections).")
            print("   Run cleanup_orphaned_sessions() when ready.")

        print("\n" + "=" * 60)
        print("  VERIFICATION COMPLETE")
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
