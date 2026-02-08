#!/usr/bin/env python3
"""
Create only the missing tables (admin_credentials and revoked_tokens)
Run this from the backend directory: python scripts/create_missing_tables.py
"""
import asyncio
import asyncpg
import sys
from pathlib import Path


async def create_missing_tables():
    # Load DATABASE_URL from .env
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        print("❌ .env file not found. Please create it from .env.example")
        sys.exit(1)

    database_url = None
    with open(env_file) as f:
        for line in f:
            if line.startswith("DATABASE_URL="):
                database_url = line.split("=", 1)[1].strip()
                break

    if not database_url or "YOUR_PROJECT_REF" in database_url:
        print("❌ DATABASE_URL not configured in .env")
        sys.exit(1)

    print(f"🔌 Connecting to database...")

    try:
        # Connect to database
        conn = await asyncpg.connect(database_url)

        print("✅ Connected to database")

        # Create admin_credentials table
        print("📝 Creating admin_credentials table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_credentials (
                id BIGSERIAL PRIMARY KEY,
                phone_number TEXT UNIQUE,
                username TEXT UNIQUE,
                added_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT at_least_one_credential CHECK (
                    phone_number IS NOT NULL OR username IS NOT NULL
                )
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_admin_credentials_phone
            ON admin_credentials(phone_number) WHERE phone_number IS NOT NULL
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_admin_credentials_username
            ON admin_credentials(username) WHERE username IS NOT NULL
        """)

        await conn.execute("""
            ALTER TABLE admin_credentials ENABLE ROW LEVEL SECURITY
        """)

        print("   ✅ admin_credentials table created")

        # Create revoked_tokens table
        print("📝 Creating revoked_tokens table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS revoked_tokens (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                jti TEXT UNIQUE NOT NULL,
                user_id TEXT,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expires_at
            ON revoked_tokens(expires_at)
        """)

        await conn.execute("""
            ALTER TABLE revoked_tokens ENABLE ROW LEVEL SECURITY
        """)

        print("   ✅ revoked_tokens table created")

        # Create cleanup function if it doesn't exist
        print("📝 Creating cleanup function...")
        await conn.execute("""
            CREATE OR REPLACE FUNCTION cleanup_expired_revoked_tokens()
            RETURNS INTEGER AS $$
            DECLARE
                deleted_count INTEGER;
            BEGIN
                DELETE FROM revoked_tokens WHERE expires_at < NOW();
                GET DIAGNOSTICS deleted_count = ROW_COUNT;
                RETURN deleted_count;
            END;
            $$ LANGUAGE plpgsql
        """)

        print("   ✅ cleanup function created")

        # Verify tables exist
        tables = await conn.fetch("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            AND tablename IN ('admin_credentials', 'revoked_tokens')
            ORDER BY tablename
        """)

        print("\n📋 Verified tables:")
        for row in tables:
            print(f"   ✓ {row['tablename']}")

        # Check if tables have data
        admin_count = await conn.fetchval("SELECT COUNT(*) FROM admin_credentials")
        token_count = await conn.fetchval("SELECT COUNT(*) FROM revoked_tokens")

        print(f"\n📊 Table status:")
        print(f"   • admin_credentials: {admin_count} rows")
        print(f"   • revoked_tokens: {token_count} rows")

        await conn.close()
        print("\n🎉 Done! You can now restart your backend server.")
        print("   The startup warnings should be gone.")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(create_missing_tables())
