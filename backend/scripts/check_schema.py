#!/usr/bin/env python3
"""Check database schema."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import db

async def check_schema():
    print("\n" + "="*60)
    print("  DATABASE SCHEMA CHECK")
    print("="*60 + "\n")

    try:
        await db.connect()

        # Check users table columns
        print("1. Checking public.users table columns...")
        result = await db.fetch("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'users'
            ORDER BY ordinal_position
        """)

        print("\n   Users table columns:")
        for row in result:
            nullable = "NULL" if row['is_nullable'] == 'YES' else "NOT NULL"
            print(f"   - {row['column_name']}: {row['data_type']} {nullable}")

        # Check telegram_id constraint
        print("\n2. Checking telegram_id nullable...")
        telegram_id_row = [r for r in result if r['column_name'] == 'telegram_id']
        if telegram_id_row:
            is_nullable = telegram_id_row[0]['is_nullable'] == 'YES'
            print(f"   telegram_id nullable: {is_nullable} {'✅' if is_nullable else '❌'}")

        # Check unique index
        print("\n3. Checking unique index on telegram_id...")
        indexes = await db.fetch("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = 'users' AND indexname LIKE '%telegram_id%'
        """)

        if indexes:
            for idx in indexes:
                print(f"   ✅ {idx['indexname']}")
                print(f"      {idx['indexdef']}")
        else:
            print("   ❌ No telegram_id index found")

        # Check constraint
        print("\n4. Checking users_must_have_identity constraint...")
        constraints = await db.fetch("""
            SELECT conname, pg_get_constraintdef(oid) as condef
            FROM pg_constraint
            WHERE conrelid = 'public.users'::regclass AND conname = 'users_must_have_identity'
        """)

        if constraints:
            for c in constraints:
                print(f"   ✅ {c['conname']}")
                print(f"      {c['condef']}")
        else:
            print("   ❌ Constraint not found")

        print("\n" + "="*60)
        print("  SCHEMA CHECK COMPLETE")
        print("="*60 + "\n")

    except Exception as e:
        print(f"\n❌ Schema check failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if hasattr(db, 'pool') and db.pool:
            await db.pool.close()

if __name__ == "__main__":
    asyncio.run(check_schema())
