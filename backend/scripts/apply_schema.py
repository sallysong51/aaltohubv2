#!/usr/bin/env python3
"""
Apply schema_actual.sql to the database
Run this from the backend directory: python scripts/apply_schema.py
"""
import asyncio
import asyncpg
import sys
from pathlib import Path


async def apply_schema():
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

    # Load schema file
    schema_file = Path(__file__).parent.parent.parent / "supabase" / "schema_actual.sql"
    if not schema_file.exists():
        print(f"❌ Schema file not found: {schema_file}")
        sys.exit(1)

    schema_sql = schema_file.read_text()

    print(f"📄 Loaded schema from: {schema_file}")
    print(f"🔌 Connecting to database...")

    try:
        # Connect to database
        conn = await asyncpg.connect(database_url)

        print("✅ Connected to database")
        print("🚀 Applying schema...")

        # Apply schema
        await conn.execute(schema_sql)

        print("✅ Schema applied successfully!")

        # Verify tables exist
        tables = await conn.fetch("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            AND tablename IN ('admin_credentials', 'revoked_tokens')
            ORDER BY tablename
        """)

        if tables:
            print("\n📋 Verified tables:")
            for row in tables:
                print(f"   ✓ {row['tablename']}")
        else:
            print("\n⚠️  Warning: Could not verify table creation")

        await conn.close()
        print("\n🎉 Done! You can now restart your backend server.")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(apply_schema())
