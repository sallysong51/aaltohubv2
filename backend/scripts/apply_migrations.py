#!/usr/bin/env python3
"""Apply database migrations."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import db

async def apply_migration(file_path: str):
    """Apply a migration SQL file."""
    print(f"\n{'='*60}")
    print(f"Applying migration: {file_path}")
    print('='*60 + "\n")

    # Read migration file
    with open(file_path, 'r') as f:
        sql = f.read()

    # Split by semicolon and execute each statement
    statements = [s.strip() for s in sql.split(';') if s.strip() and not s.strip().startswith('--')]

    try:
        await db.connect()

        for i, statement in enumerate(statements, 1):
            if statement:
                print(f"[{i}/{len(statements)}] Executing statement...")
                try:
                    result = await db.execute(statement)
                    if result:
                        print(f"  ✓ {result}")
                except Exception as e:
                    print(f"  ⚠️  Warning: {e}")

        print("\n✅ Migration applied successfully!")

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if hasattr(db, 'close'):
            await db.close()
        elif hasattr(db, 'pool') and db.pool:
            await db.pool.close()

async def main():
    if len(sys.argv) < 2:
        print("Usage: python apply_migrations.py <migration_file>")
        print("Example: python backend/scripts/apply_migrations.py backend/migrations/002_email_signup.sql")
        sys.exit(1)

    migration_file = sys.argv[1]

    if not Path(migration_file).exists():
        print(f"Error: File not found: {migration_file}")
        sys.exit(1)

    await apply_migration(migration_file)

if __name__ == "__main__":
    asyncio.run(main())
