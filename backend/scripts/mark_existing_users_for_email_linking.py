#!/usr/bin/env python3
"""
Mark all existing users for forced email linking on next login.

This script sets email_link_required = TRUE for all users who don't have
an auth_user_id linked yet. These users will be forced to link an email
address the next time they log in via Telegram.

Usage:
    python backend/scripts/mark_existing_users_for_email_linking.py

Safe to run multiple times (UPDATE with WHERE condition).
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import db


async def mark_users():
    """Mark all users without auth_user_id for email linking."""
    print("[EMAIL LINKING] Connecting to database...")
    await db.connect()

    try:
        # Count users before
        total = await db.fetchval("SELECT COUNT(*) FROM users")
        already_linked = await db.fetchval(
            "SELECT COUNT(*) FROM users WHERE auth_user_id IS NOT NULL"
        )
        print(f"[EMAIL LINKING] Total users: {total}")
        print(f"[EMAIL LINKING] Already linked: {already_linked}")

        # Mark users for email linking
        result = await db.execute(
            """UPDATE users
               SET email_link_required = TRUE
               WHERE auth_user_id IS NULL"""
        )

        # Parse result (format: "UPDATE N")
        count = result.split()[-1] if result else "0"
        print(f"[EMAIL LINKING] Marked {count} users for email linking")

        # Verify
        marked = await db.fetchval(
            "SELECT COUNT(*) FROM users WHERE email_link_required = TRUE"
        )
        print(f"[EMAIL LINKING] Total users needing email link: {marked}")
        print("[EMAIL LINKING] ✓ Complete")

    except Exception as e:
        print(f"[EMAIL LINKING] ✗ Error: {e}")
        raise
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(mark_users())
