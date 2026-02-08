#!/usr/bin/env python3
"""
Preflight check — validates venv, packages, and env vars before starting uvicorn.
Exit 0 = all clear. Exit 1 = blocking issue found.
"""
import sys
import os
import importlib

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)

REQUIRED_MODULES = [
    "asyncpg", "fastapi", "uvicorn", "pydantic_settings", "telethon",
    "sentry_sdk", "httpx", "jwt",
]
REQUIRED_ENV = [
    "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "JWT_SECRET",
    "TELEGRAM_API_ID", "TELEGRAM_API_HASH", "ENCRYPTION_KEY", "DATABASE_URL",
]

errors = []
warnings = []


def check(label, condition, fix_msg):
    if not condition:
        errors.append(f"{label}\n        Fix: {fix_msg}")


def warn(label, msg):
    warnings.append(f"{label} — {msg}")


# 1. venv exists
venv_python = os.path.join(BACKEND_DIR, "venv", "bin", "python")
check(
    "venv directory exists",
    os.path.isfile(venv_python),
    "cd backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt",
)

# 2. Critical Python packages importable
for mod in REQUIRED_MODULES:
    try:
        importlib.import_module(mod)
    except ImportError:
        errors.append(
            f"Cannot import '{mod}'\n"
            "        Fix: source venv/bin/activate && pip install -r requirements.txt"
        )

# 3. .env file exists
env_path = os.path.join(BACKEND_DIR, ".env")
if not os.path.isfile(env_path):
    errors.append(
        ".env file missing\n"
        "        Fix: cp .env.example .env && edit with your credentials"
    )
else:
    # 4. Required env vars set
    try:
        from dotenv import dotenv_values
        env = {**dotenv_values(env_path), **os.environ}
    except ImportError:
        env = os.environ

    for var in REQUIRED_ENV:
        val = env.get(var, "")
        if not val:
            errors.append(f"{var} not set\n        Fix: add {var}=... to backend/.env")

    # 5. DATABASE_URL format check
    db_url = env.get("DATABASE_URL", "")
    if db_url and not db_url.startswith(("postgresql://", "postgres://")):
        errors.append(
            f"DATABASE_URL has invalid scheme (starts with: {db_url[:15]}...)\n"
            "        Fix: must start with postgresql:// or postgres://"
        )

    # 6. DATABASE_URL connectivity probe (non-blocking warning)
    if db_url and db_url.startswith(("postgresql://", "postgres://")):
        try:
            import asyncio
            import asyncpg

            async def _probe():
                conn = await asyncio.wait_for(
                    asyncpg.connect(dsn=db_url), timeout=5.0
                )
                await conn.close()

            asyncio.run(_probe())
        except Exception as e:
            err_str = str(e)
            if "Tenant or user not found" in err_str:
                warn("DATABASE_URL connectivity",
                     "Supabase project may be PAUSED — wake it at https://app.supabase.com")
            else:
                warn("DATABASE_URL connectivity", f"Cannot connect: {err_str[:100]}")


# Print results
print()
print("=" * 50)
print("  AALTOHUB v2 — PREFLIGHT CHECK")
print("=" * 50)

if errors:
    print(f"\n  {len(errors)} error(s) found:\n")
    for e in errors:
        print(f"  [FAIL] {e}")
    print()
    print("  Backend cannot start until these are resolved.")

if warnings:
    print(f"\n  {len(warnings)} warning(s):\n")
    for w in warnings:
        print(f"  [WARN] {w}")

if not errors and not warnings:
    print("\n  All checks passed.")

print()
print("=" * 50)
print()

sys.exit(1 if errors else 0)
