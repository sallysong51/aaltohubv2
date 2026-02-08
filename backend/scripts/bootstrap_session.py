#!/usr/bin/env python3
"""
Bootstrap a Telegram session for the crawler — independent of the web app.

Performs headless Telegram authentication on the server and stores the
encrypted session directly in the database. The crawler will auto-detect
the new session within 60 seconds (or restart it manually).

Usage (interactive):
    cd backend && source venv/bin/activate
    python scripts/bootstrap_session.py --phone +358449598622

Usage (non-interactive, e.g. via SSH):
    # Step 1: Send code (will fail at input, but code is sent to Telegram)
    python scripts/bootstrap_session.py --phone +358449598622 --send-code
    # Step 2: Enter the code received
    python scripts/bootstrap_session.py --phone +358449598622 --code 12345
    # If 2FA is enabled:
    python scripts/bootstrap_session.py --phone +358449598622 --code 12345 --password YOUR2FA
"""
import argparse
import asyncio
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
    PhoneNumberInvalidError,
    PhoneNumberBannedError,
)

from app.config import settings
from app.encryption import session_encryption, ENCRYPTION_VERSION


async def main(phone: str, force: bool = False, code: str = None, password: str = None, send_code_only: bool = False) -> None:
    if not phone.startswith("+"):
        print("ERROR: Phone must include country code (e.g. +358449598622)")
        sys.exit(1)

    if not settings.ENCRYPTION_KEY:
        print("ERROR: ENCRYPTION_KEY is not set in .env")
        sys.exit(1)

    # --- Connect to DB ---
    print(f"Connecting to database...")
    try:
        conn = await asyncpg.connect(settings.DATABASE_URL, statement_cache_size=0)
    except Exception as e:
        print(f"ERROR: Cannot connect to database: {e}")
        sys.exit(1)

    try:
        # --- Check existing user/session ---
        existing_user = await conn.fetchrow(
            "SELECT id, first_name, username FROM users WHERE phone_number = $1", phone
        )
        if existing_user:
            session_row = await conn.fetchrow(
                "SELECT id FROM telethon_sessions WHERE user_id = $1",
                existing_user["id"],
            )
            if session_row and not force:
                name = existing_user.get("first_name") or existing_user.get("username") or "?"
                print(f"Session already exists for {name} (user_id={existing_user['id']}).")
                if code:
                    # Non-interactive mode: auto-overwrite
                    print("Non-interactive mode: overwriting existing session.")
                else:
                    confirm = input("Overwrite? [y/N]: ").strip().lower()
                    if confirm != "y":
                        print("Aborted.")
                        return

        # --- Telegram authentication ---
        print(f"\nAuthenticating with Telegram for {phone}...")
        print("A code will be sent to your Telegram app.\n")

        client = TelegramClient(
            StringSession(""),
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
        )
        await client.connect()

        state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bootstrap_state")

        if code and os.path.exists(state_file):
            # Non-interactive step 2: restore session + hash from step 1
            import json
            with open(state_file, "r") as f:
                state = json.load(f)
            phone_code_hash = state["phone_code_hash"]
            saved_session = state["session_string"]
            os.remove(state_file)

            # Reconnect using the SAME session that sent the code
            await client.disconnect()
            client = TelegramClient(
                StringSession(saved_session),
                settings.TELEGRAM_API_ID,
                settings.TELEGRAM_API_HASH,
            )
            await client.connect()
            print(f"Restored session from previous --send-code run")
        else:
            # Send a new code
            try:
                sent = await client.send_code_request(phone)
                phone_code_hash = sent.phone_code_hash
                print(f"Code sent to Telegram app (phone_code_hash: {phone_code_hash[:8]}...)")
            except PhoneNumberInvalidError:
                print("ERROR: Invalid phone number format.")
                await client.disconnect()
                return
            except PhoneNumberBannedError:
                print("ERROR: This phone number is banned by Telegram.")
                await client.disconnect()
                return
            except FloodWaitError as e:
                print(f"ERROR: Telegram rate limit. Retry after {e.seconds} seconds.")
                await client.disconnect()
                return

            if send_code_only:
                # Save session + hash for step 2
                import json
                with open(state_file, "w") as f:
                    json.dump({
                        "phone_code_hash": phone_code_hash,
                        "session_string": client.session.save(),
                    }, f)
                print("\n--send-code mode: Code has been sent to your Telegram app.")
                print(f"Now run again with: --code <THE_CODE>")
                await client.disconnect()
                return

        if not code:
            code = input("Enter the code from Telegram: ").strip()

        try:
            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            if not password:
                password = getpass.getpass("2FA password required: ")
            await client.sign_in(password=password)
        except PhoneCodeInvalidError:
            print("ERROR: Invalid code.")
            await client.disconnect()
            return
        except PhoneCodeExpiredError:
            print("ERROR: Code expired. Run with --send-code again.")
            await client.disconnect()
            return

        me = await client.get_me()
        session_string = client.session.save()
        await client.disconnect()

        print(f"\nAuthenticated as: {me.first_name} (@{me.username}), Telegram ID: {me.id}")

        # --- Upsert user record ---
        user_id = await conn.fetchval(
            """INSERT INTO users (telegram_id, phone_number, username, first_name, last_name, role)
               VALUES ($1, $2, $3, $4, $5, 'admin')
               ON CONFLICT (telegram_id) WHERE telegram_id IS NOT NULL
               DO UPDATE SET phone_number = $2, username = $3, first_name = $4, last_name = $5, role = 'admin'
               RETURNING id""",
            me.id, me.phone, me.username, me.first_name, me.last_name,
        )
        print(f"User record: id={user_id}, role=admin")

        # --- Encrypt and store session ---
        aad = str(user_id)
        encrypted = session_encryption.encrypt(session_string, aad=aad)

        await conn.execute(
            """INSERT INTO telethon_sessions (user_id, session_data, key_hash)
               VALUES ($1, $2, $3)
               ON CONFLICT (user_id)
               DO UPDATE SET session_data = $2, key_hash = $3, updated_at = NOW()""",
            user_id, encrypted, ENCRYPTION_VERSION,
        )
        print(f"Session encrypted and stored (key_hash={ENCRYPTION_VERSION})")

        # --- Ensure admin_credentials entry ---
        if me.phone:
            await conn.execute(
                """INSERT INTO admin_credentials (phone_number, username)
                   VALUES ($1, $2)
                   ON CONFLICT (phone_number) DO NOTHING""",
                me.phone, me.username,
            )

        # --- Verify by decrypting ---
        verify_row = await conn.fetchrow(
            "SELECT session_data FROM telethon_sessions WHERE user_id = $1", user_id
        )
        decrypted = session_encryption.decrypt(verify_row["session_data"], aad=aad)
        assert decrypted == session_string, "Verification FAILED: decrypted session does not match!"

        print(f"\n{'=' * 50}")
        print(f"SUCCESS: Session bootstrapped for {me.first_name} (@{me.username})")
        print(f"  User ID: {user_id}")
        print(f"  Telegram ID: {me.id}")
        print(f"  Role: admin")
        print(f"{'=' * 50}")
        print(f"\nThe crawler will auto-detect this session within 60 seconds.")
        print(f"Or restart manually: sudo systemctl restart aaltohub-live-crawler")

    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap a Telegram session for the crawler")
    parser.add_argument("--phone", required=True, help="Phone number with country code (e.g. +358449598622)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing session without prompting")
    parser.add_argument("--code", type=str, default=None, help="Telegram verification code (for non-interactive use)")
    parser.add_argument("--password", type=str, default=None, help="2FA password (for non-interactive use)")
    parser.add_argument("--send-code", action="store_true", dest="send_code", help="Only send the code, then exit")
    args = parser.parse_args()

    asyncio.run(main(args.phone, args.force, args.code, args.password, args.send_code))
