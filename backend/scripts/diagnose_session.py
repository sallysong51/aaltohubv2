#!/usr/bin/env python3
"""
Diagnostic script to check Telegram session status for a user.

Usage:
    python backend/scripts/diagnose_session.py <user_id>
    python backend/scripts/diagnose_session.py --email <email>
"""
import asyncio
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import db
from app.config import settings


async def diagnose_user_session(user_id: int = None, email: str = None):
    """Diagnose Telegram session status for a user."""
    await db._ensure_pool()

    try:
        # Look up user
        if email:
            user_row = await db.fetchrow(
                "SELECT * FROM users WHERE auth_user_id = (SELECT id FROM auth.users WHERE email = $1)",
                email
            )
            if not user_row:
                print(f"❌ No user found with email: {email}")
                return
        elif user_id:
            user_row = await db.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
            if not user_row:
                print(f"❌ No user found with id: {user_id}")
                return
        else:
            print("❌ Must provide either --user-id or --email")
            return

        user_id = user_row["id"]
        telegram_id = user_row.get("telegram_id")
        auth_user_id = user_row.get("auth_user_id")

        print(f"\n{'='*60}")
        print(f"User Diagnostic Report")
        print(f"{'='*60}")
        print(f"User ID:       {user_id}")
        print(f"Telegram ID:   {telegram_id}")
        print(f"Auth User ID:  {auth_user_id}")
        print(f"Username:      {user_row.get('username')}")
        print(f"Phone:         {user_row.get('phone_number')}")
        print(f"Email Link:    {user_row.get('email_link_required')}")
        print(f"{'='*60}\n")

        # Check telegram_connections
        tc_rows = await db.fetch(
            "SELECT * FROM telegram_connections WHERE user_id = $1",
            user_id
        )
        print(f"📋 telegram_connections: {len(tc_rows)} row(s)")
        for i, row in enumerate(tc_rows, 1):
            print(f"  [{i}] telegram_user_id={row['telegram_user_id']}")
            print(f"      auth_user_id={row['auth_user_id']}")
            print(f"      key_hash={row['key_hash']}")
            print(f"      session_encrypted length={len(row['session_encrypted']) if row['session_encrypted'] else 0}")
            print(f"      last_used_at={row['last_used_at']}")

        # Check telethon_sessions
        ts_rows = await db.fetch(
            "SELECT * FROM telethon_sessions WHERE user_id = $1",
            user_id
        )
        print(f"\n📋 telethon_sessions: {len(ts_rows)} row(s)")
        for i, row in enumerate(ts_rows, 1):
            print(f"  [{i}] key_hash={row['key_hash']}")
            print(f"      session_data length={len(row['session_data']) if row['session_data'] else 0}")
            print(f"      updated_at={row['updated_at']}")

        # Recommendations
        print(f"\n{'='*60}")
        print("Recommendations:")
        print(f"{'='*60}")

        if not telegram_id:
            print("⚠️  No telegram_id set — user has no Telegram account linked")
        elif len(tc_rows) == 0 and len(ts_rows) == 0:
            print("❌ No sessions found — user needs to re-login via Telegram")
        elif len(tc_rows) > 0:
            print("✅ Session found in telegram_connections (new system)")
        elif len(ts_rows) > 0:
            print("⚠️  Session found in telethon_sessions (legacy system)")
            print("    Should be migrated to telegram_connections on next email link")

        if auth_user_id and len(tc_rows) == 0:
            print("⚠️  User has auth_user_id but no telegram_connections entry")
            print("    Email linking may have failed — user should re-link email")

    finally:
        await db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Diagnose Telegram session status")
    parser.add_argument("user_id", nargs="?", type=int, help="User ID to diagnose")
    parser.add_argument("--email", type=str, help="Email to lookup user")

    args = parser.parse_args()

    if not args.user_id and not args.email:
        parser.print_help()
        sys.exit(1)

    asyncio.run(diagnose_user_session(user_id=args.user_id, email=args.email))
