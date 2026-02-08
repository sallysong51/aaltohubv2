#!/usr/bin/env python3
"""
Auto-register all Telegram groups that admin accounts belong to.

Loads admin sessions from DB, fetches dialogs via Telethon, and inserts
all groups/channels into the groups + user_groups + crawler_status tables.

Usage:
    cd backend && source venv/bin/activate
    python scripts/auto_register_groups.py
    python scripts/auto_register_groups.py --dry-run   # preview only
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat

from app.config import settings
from app.encryption import session_encryption, ENCRYPTION_VERSION


async def main(dry_run: bool = False) -> None:
    if not settings.ENCRYPTION_KEY:
        print("ERROR: ENCRYPTION_KEY is not set in .env")
        sys.exit(1)

    print("Connecting to database...")
    try:
        conn = await asyncpg.connect(settings.DATABASE_URL, statement_cache_size=0)
    except Exception as e:
        print(f"ERROR: Cannot connect to database: {e}")
        sys.exit(1)

    try:
        # Find admin users with sessions
        admin_rows = await conn.fetch("SELECT id, first_name, username FROM users WHERE role = 'admin'")
        if not admin_rows:
            print("ERROR: No admin users found. Run bootstrap_session.py first.")
            return

        print(f"Found {len(admin_rows)} admin user(s)")

        for admin in admin_rows:
            admin_id = admin["id"]
            admin_name = admin.get("first_name") or admin.get("username") or str(admin_id)

            # Try telethon_sessions first
            row = await conn.fetchrow(
                "SELECT session_data, key_hash FROM telethon_sessions WHERE user_id = $1", admin_id
            )
            if not row:
                print(f"  Skipping {admin_name} (no session)")
                continue

            aad = str(admin_id)
            try:
                if row["key_hash"] == ENCRYPTION_VERSION:
                    session_str = session_encryption.decrypt(row["session_data"], aad=aad)
                else:
                    from app.encryption import get_legacy_encryption
                    session_str = get_legacy_encryption().decrypt(row["session_data"])
            except Exception as e:
                print(f"  ERROR: Cannot decrypt session for {admin_name}: {e}")
                continue

            print(f"\nConnecting as {admin_name}...")
            client = TelegramClient(StringSession(session_str), settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH)
            await client.connect()

            try:
                me = await client.get_me()
                if not me:
                    print(f"  ERROR: Auth failed for {admin_name}")
                    continue
                print(f"  Authenticated as {me.first_name} (@{me.username})")

                dialogs = await asyncio.wait_for(client.get_dialogs(), timeout=30)
                registered = 0
                skipped = 0

                for d in dialogs:
                    entity = d.entity
                    if not isinstance(entity, (Channel, Chat)):
                        continue

                    gid = entity.id
                    name = d.title or "Unknown"
                    is_channel = getattr(entity, "broadcast", False)
                    username = getattr(entity, "username", None)
                    visibility = "public" if username else "private"
                    gtype = "channel" if is_channel else "supergroup"
                    members = getattr(entity, "participants_count", None)

                    if dry_run:
                        existing = await conn.fetchrow("SELECT id FROM groups WHERE id = $1", gid)
                        status = "EXISTS" if existing else "NEW"
                        print(f"  [{status}] {name} ({gtype}, {members or '?'} members)")
                        if not existing:
                            registered += 1
                        else:
                            skipped += 1
                        continue

                    # Upsert into groups
                    await conn.execute("""
                        INSERT INTO groups (id, name, username, visibility, type, member_count, crawl_enabled, registered_by)
                        VALUES ($1, $2, $3, $4, $5, $6, true, $7)
                        ON CONFLICT (id) DO UPDATE SET name=$2, username=$3, member_count=$6, updated_at=NOW()
                    """, gid, name, username, visibility, gtype, members, admin_id)

                    # Link to admin user
                    await conn.execute("""
                        INSERT INTO user_groups (user_id, group_id)
                        VALUES ($1, $2) ON CONFLICT (user_id, group_id) DO NOTHING
                    """, admin_id, gid)

                    # Ensure crawler_status row
                    await conn.execute("""
                        INSERT INTO crawler_status (group_id, status, is_enabled, error_count, initial_crawl_progress, initial_crawl_total)
                        VALUES ($1, 'inactive', TRUE, 0, 0, 0) ON CONFLICT (group_id) DO NOTHING
                    """, gid)

                    registered += 1
                    print(f"  OK: {name}")

                print(f"\n  {admin_name}: {registered} groups {'would be ' if dry_run else ''}registered, {skipped} already exist")

            finally:
                await client.disconnect()

        # Summary
        total_groups = await conn.fetchval("SELECT COUNT(*) FROM groups")
        total_links = await conn.fetchval("SELECT COUNT(*) FROM user_groups")
        print(f"\n{'=' * 50}")
        print(f"Total groups in DB: {total_groups}")
        print(f"Total user_group links: {total_links}")
        if not dry_run:
            print(f"\nRestart crawler to pick up changes:")
            print(f"  sudo systemctl restart aaltohub-live-crawler")
        print(f"{'=' * 50}")

    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-register all admin Telegram groups")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
