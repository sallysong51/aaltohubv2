"""
One-time migration: Copy admin Telegram sessions to telegram_connections for user 4 (song52114@gmail.com).

This script:
1. Finds admin users (user 1, user 2) with sessions in telethon_sessions
2. Decrypts each session using the original user_id as AAD
3. Re-encrypts with user 4's ID as AAD
4. Inserts into telegram_connections for user 4
5. Makes user 4 an admin

Usage: cd backend && source venv/bin/activate && python scripts/migrate_sessions.py
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.encryption import session_encryption, ENCRYPTION_VERSION, get_legacy_encryption

TARGET_USER_ID = 4  # song52114@gmail.com


async def main():
    import asyncpg
    conn = await asyncpg.connect(settings.DATABASE_URL)

    try:
        # 1. Verify target user exists
        target_user = await conn.fetchrow("SELECT * FROM users WHERE id = $1", TARGET_USER_ID)
        if not target_user:
            print(f"ERROR: User {TARGET_USER_ID} not found!")
            return

        print(f"Target user: id={TARGET_USER_ID}, email auth_user_id={target_user['auth_user_id']}")

        # 2. Make target user admin
        await conn.execute(
            "UPDATE users SET role = 'admin' WHERE id = $1",
            TARGET_USER_ID,
        )
        print(f"✓ User {TARGET_USER_ID} role set to 'admin'")

        # 3. Find admin users with sessions
        admin_sessions = await conn.fetch(
            """SELECT u.id, u.first_name, u.username, u.telegram_id,
                      ts.session_data, ts.key_hash
               FROM users u
               JOIN telethon_sessions ts ON ts.user_id = u.id
               WHERE u.role = 'admin' AND u.id != $1""",
            TARGET_USER_ID,
        )

        if not admin_sessions:
            print("No admin sessions found to migrate.")
            return

        print(f"\nFound {len(admin_sessions)} admin session(s) to migrate:")

        for row in admin_sessions:
            source_user_id = row["id"]
            source_name = row["first_name"] or "?"
            source_username = row["username"] or "N/A"
            telegram_id = row["telegram_id"]

            print(f"\n  Source: user {source_user_id} ({source_name} @{source_username}), telegram_id={telegram_id}")

            # Decrypt with source user's AAD
            source_aad = str(source_user_id)
            try:
                if row["key_hash"] == ENCRYPTION_VERSION:
                    session_string = session_encryption.decrypt(row["session_data"], aad=source_aad)
                else:
                    legacy = get_legacy_encryption()
                    session_string = legacy.decrypt(row["session_data"])
                print(f"    ✓ Decrypted (session length: {len(session_string)})")
            except Exception as e:
                print(f"    ✗ Decryption failed: {e}")
                continue

            # Re-encrypt with target user's AAD
            target_aad = str(TARGET_USER_ID)
            encrypted = session_encryption.encrypt(session_string, aad=target_aad)
            key_hash = session_encryption.get_key_hash()

            # Mask phone number
            phone = None  # admin sessions may not have phone stored in users table
            phone_masked = None

            # Insert into telegram_connections
            import uuid
            connection_id = str(uuid.uuid4())

            await conn.execute(
                """INSERT INTO telegram_connections
                   (id, user_id, telegram_user_id, phone_masked, username,
                    session_encrypted, key_hash, first_name, last_name)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                   ON CONFLICT (user_id, telegram_user_id)
                   DO UPDATE SET session_encrypted = $6, key_hash = $7,
                                 username = $5, first_name = $8, updated_at = NOW()""",
                connection_id,
                TARGET_USER_ID,
                telegram_id,
                phone_masked,
                row["username"],
                encrypted,
                key_hash,
                row["first_name"],
                row.get("last_name"),
            )
            print(f"    ✓ Inserted into telegram_connections (id={connection_id[:8]}...)")

        # 4. Verify
        connections = await conn.fetch(
            "SELECT id, telegram_user_id, username, first_name FROM telegram_connections WHERE user_id = $1",
            TARGET_USER_ID,
        )
        print(f"\n=== Result: User {TARGET_USER_ID} now has {len(connections)} Telegram connection(s):")
        for c in connections:
            print(f"  - {c['first_name']} (@{c['username']}) [tg_id={c['telegram_user_id']}, conn={str(c['id'])[:8]}...]")

        print("\n✓ Migration complete!")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
