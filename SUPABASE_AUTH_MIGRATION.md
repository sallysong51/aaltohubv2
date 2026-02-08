# Supabase Auth Migration Guide

## Overview

This guide covers the migration from custom JWT + Telegram-only authentication to Supabase Auth (email/password) as primary authentication, with Telegram as an optional connection.

**Migration Status:** ✅ **IMPLEMENTATION COMPLETE**

All phases (1-4) are implemented and ready for testing/deployment.

---

## Architecture Changes

### Before Migration
- **Authentication:** Telegram-only (phone → SMS code → 2FA)
- **JWT:** Custom implementation (HS256, 60min access + 30day refresh)
- **Sessions:** `telethon_sessions` table
- **User ID:** BIGSERIAL (used as encryption AAD)

### After Migration
- **Authentication:** Supabase Auth (email + password) OR Telegram (both work)
- **JWT:** Still custom (for API access during transition)
- **Sessions:**
  - New: `telegram_connections` table (for Supabase Auth users)
  - Legacy: `telethon_sessions` (fallback during migration)
- **User ID:** BIGSERIAL preserved (encryption AAD unchanged)

---

## Deployment Steps

### Step 1: Database Migration

**Apply schema changes:**

```bash
# Connect to your Supabase database (or use SQL Editor in Supabase Dashboard)
psql "postgresql://postgres.xxx:[YOUR-PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"

# Apply migration
\i backend/migrations/001_add_supabase_auth.sql
```

**What it does:**
- Adds `auth_user_id`, `email_link_required`, `email_linked_at` columns to `users`
- Creates `telegram_connections` table
- Creates `email_linking_attempts` table
- Marks existing users with `email_link_required = TRUE`

**Verify:**
```sql
-- Check new columns exist
\d users

-- Check new tables exist
\dt telegram_connections
\dt email_linking_attempts

-- Check existing users marked for migration
SELECT COUNT(*) FROM users WHERE email_link_required = TRUE;
```

### Step 2: Backend Deployment

**Install dependencies (if needed):**
```bash
cd backend
pip install -r requirements.txt  # supabase-py should already be installed
```

**Verify environment variables:**
```bash
# Check backend/.env has:
# - SUPABASE_URL
# - SUPABASE_SERVICE_ROLE_KEY
# - JWT_SECRET (existing)
# - ENCRYPTION_KEY (existing, NEVER change this!)
```

**Deploy backend:**
```bash
# Development
npm run dev

# Production (systemd)
sudo systemctl restart aaltohub-api
sudo systemctl status aaltohub-api
```

**Check logs:**
```bash
# Should see:
# [SESSION MIGRATION] Starting session migration task...
# [SESSION MIGRATION] Found X sessions to migrate (or "No sessions need migration")
# [SESSION MIGRATION] Complete: X migrated, 0 errors
```

### Step 3: Frontend Deployment

**Build and deploy:**
```bash
cd client
npm run build

# For Vercel (if using)
vercel --prod
```

**Verify routes:**
- `/login` - Should show email/Telegram tabs
- `/email-linking` - Should load (will redirect if not authenticated)

### Step 4: Verification

**Run verification script:**
```bash
python backend/scripts/verify_migration.py
```

**Expected output:**
```
Total linked users (auth_user_id set): 0  # (no one linked yet)
Users with telegram_connections:       0
Users missing telegram_connections:    0
Orphaned telethon_sessions (cleanup):  0

✓ All users have successfully migrated sessions!
```

---

## Testing Checklist

### Pre-Deployment Testing (Staging)

- [ ] **Database migration applied successfully**
  ```bash
  psql -c "SELECT auth_user_id, email_link_required FROM users LIMIT 1"
  ```

- [ ] **Backend starts without errors**
  ```bash
  grep -i "error\|exception" backend.log
  ```

- [ ] **Session migration runs on startup**
  ```bash
  grep "SESSION MIGRATION" backend.log
  ```

### Post-Deployment Testing (Production)

#### Test 1: Existing Telegram User (Forced Email Linking)

1. **Login with existing Telegram account:**
   - Go to `/login`
   - Switch to "텔레그램 로그인" tab
   - Enter phone number → SMS code → (2FA if enabled)
   - ✅ Should redirect to `/email-linking` (forced migration)

2. **Link email:**
   - Enter email (e.g., `test@aalto.fi`)
   - Enter password (min 8 chars)
   - Confirm password
   - ✅ Should show success toast
   - ✅ Should redirect to `/` (home)
   - ✅ If admin: redirect to `/admin`
   - ✅ If user with groups: redirect to `/feed`

3. **Verify email login works:**
   - Logout
   - Go to `/login`
   - Switch to "이메일 로그인" tab
   - Enter email + password
   - ✅ Should login successfully
   - ✅ Should show same user data

4. **Verify Telegram login still works:**
   - Logout
   - Go to `/login`
   - Switch to "텔레그램 로그인" tab
   - Login with phone
   - ✅ Should NOT show email linking page (already linked)
   - ✅ Should go directly to home

#### Test 2: Session Preservation

1. **Before email linking:**
   - Note the user's registered groups
   - Check crawler is running for their groups

2. **After email linking:**
   - ✅ All groups should still be visible
   - ✅ Crawler should still work (messages coming in)
   - ✅ Group settings should be preserved

#### Test 3: New User Flow

1. **New user with no account:**
   - Go to `/login`
   - Try email login → ✅ Should get "계정을 찾을 수 없습니다" error
   - Switch to Telegram login
   - Complete phone verification
   - ✅ Should be forced to link email
   - Link email
   - ✅ Can now use email login

#### Test 4: Rate Limiting

1. **Email linking rate limit:**
   - Try linking with wrong email 5 times in a row
   - ✅ 6th attempt should be blocked with 429 error
   - Wait 15 minutes
   - ✅ Should be able to try again

2. **Email login rate limit:**
   - Try wrong password multiple times
   - ✅ Should follow existing rate limiting (5 attempts / 5 min)

#### Test 5: Admin Features

1. **Admin login:**
   - Login as admin (Telegram or email)
   - ✅ Should go to `/admin` dashboard
   - ✅ Crawler management should work
   - ✅ User management should work

#### Test 6: Migration Verification

```bash
# After 1+ users have linked email
python backend/scripts/verify_migration.py

# Should show:
# Total linked users: 1+
# Users with telegram_connections: 1+
# Missing TC: 0
# Orphaned sessions: 1+ (old sessions that can be cleaned up)
```

---

## Rollback Instructions

### If Issues Detected Within 24 Hours

**Option 1: Full Rollback (remove all changes)**

```bash
# 1. Revert database
psql -f backend/migrations/001_rollback.sql

# 2. Revert backend code
git revert <commit-hash>  # Revert Phases 2-4 commits

# 3. Revert frontend code
git revert <commit-hash>  # Revert Phase 3 commits

# 4. Redeploy
npm run dev  # or systemctl restart
```

**Option 2: Partial Rollback (disable email auth, keep DB schema)**

```bash
# 1. Set flag in backend/app/config.py
SUPABASE_AUTH_ENABLED = False

# 2. Redeploy backend
npm run dev

# Result: Email login disabled, Telegram-only continues working
# Users who already linked can still use Telegram auth
```

### Rollback Verification

```bash
# Check users table reverted
psql -c "\d users"  # Should NOT show auth_user_id column

# Check Telegram login still works
curl -X POST http://localhost:8000/api/auth/send-code \
  -H "Content-Type: application/json" \
  -d '{"phone_or_username": "+358..."}'
```

---

## Monitoring

### Key Metrics to Watch

**Backend Logs:**
```bash
# Session migration progress
grep "SESSION MIGRATION" backend.log

# Email linking attempts
grep "EMAIL LINKING\|link-email" backend.log

# Authentication errors
grep "401\|403\|TelegramAuthError" backend.log
```

**Database Queries:**
```sql
-- Email linking progress
SELECT
  COUNT(*) FILTER (WHERE auth_user_id IS NOT NULL) AS linked,
  COUNT(*) FILTER (WHERE email_link_required = TRUE) AS pending,
  COUNT(*) AS total
FROM users;

-- Session distribution
SELECT
  (SELECT COUNT(*) FROM telegram_connections) AS new_sessions,
  (SELECT COUNT(*) FROM telethon_sessions) AS legacy_sessions;

-- Failed email linking attempts
SELECT user_id, email, attempt_count, created_at
FROM email_linking_attempts
WHERE attempt_count > 3
ORDER BY created_at DESC;
```

### Success Criteria

- ✅ **Week 1:** 10-20% of users linked email
- ✅ **Week 2:** 50%+ of users linked email
- ✅ **Week 3:** 80%+ of users linked email
- ✅ **Week 4:** 95%+ of users linked email

### Error Budget

- **Session migration failures:** < 1%
- **Email linking failures:** < 5% (some expected due to invalid emails)
- **Authentication errors:** < 0.1% increase from baseline

---

## Post-Migration Cleanup (Optional)

**After 30+ days and 95%+ migration:**

```bash
# 1. Verify all sessions migrated
python backend/scripts/verify_migration.py

# 2. Clean up orphaned telethon_sessions
python backend/scripts/cleanup_orphaned_sessions.py
# ⚠️  WARNING: This is DESTRUCTIVE. Only run after verification!

# 3. (Future) Remove custom JWT and switch to Supabase Auth tokens
# This is Phase 6, deferred for now
```

---

## Troubleshooting

### Issue: Session migration not running on startup

**Symptoms:** No "SESSION MIGRATION" logs on backend startup

**Causes:**
1. Database not connected
2. Import error

**Fix:**
```bash
# Check database connection
grep "Database: connected" backend.log

# Check for import errors
grep "Could not start session migration" backend.log

# Manually run migration
python backend/scripts/verify_migration.py
```

### Issue: "Cannot decrypt legacy session" errors

**Symptoms:** Users getting 401 errors after email linking

**Cause:** ENCRYPTION_KEY changed (breaking change!)

**Fix:**
```bash
# Check ENCRYPTION_KEY in backend/.env
# It MUST be: ubxeKMxoi4uH-tilff8l-LVbnEqO4_5BWI9M-u-4El4

# If changed, revert to original value and restart backend
```

### Issue: Email already in use (false positive)

**Symptoms:** User gets "이메일이 이미 사용 중입니다" error but hasn't registered

**Cause:** Email exists in Supabase Auth but not linked in public.users

**Fix:**
```sql
-- Find orphaned auth.users
SELECT email FROM auth.users
WHERE id NOT IN (SELECT auth_user_id FROM public.users WHERE auth_user_id IS NOT NULL);

-- Manual cleanup (if confirmed orphaned)
-- Use Supabase Dashboard → Authentication → Users → Delete
```

### Issue: Users stuck on email linking page

**Symptoms:** User forced to link email but already linked

**Cause:** `email_link_required` flag not cleared

**Fix:**
```sql
-- Check user's status
SELECT id, email_link_required, auth_user_id FROM users WHERE telegram_id = <TELEGRAM_ID>;

-- If auth_user_id is set but flag still TRUE, clear it:
UPDATE users SET email_link_required = FALSE WHERE id = <USER_ID>;
```

---

## Files Modified/Created

### Schema (1 file)
- `supabase/schema_actual.sql` ✅

### Backend (8 files)
- `backend/app/supabase_auth.py` ✅ (NEW)
- `backend/app/routes/email_linking.py` ✅ (NEW)
- `backend/app/session_migration.py` ✅ (NEW)
- `backend/app/routes/auth.py` ✅ (MODIFIED - email login)
- `backend/app/telegram_client.py` ✅ (MODIFIED - telegram_connections check)
- `backend/app/models.py` ✅ (MODIFIED - email models)
- `backend/app/main.py` ✅ (MODIFIED - router + migration task)

### Frontend (4 files)
- `client/src/pages/EmailLinking.tsx` ✅ (NEW)
- `client/src/pages/Login.tsx` ✅ (MODIFIED - tabs)
- `client/src/App.tsx` ✅ (MODIFIED - route + checkpoint)
- `client/src/lib/api.ts` ✅ (MODIFIED - email endpoints)

### Migration Scripts (5 files)
- `backend/migrations/001_add_supabase_auth.sql` ✅
- `backend/migrations/001_rollback.sql` ✅
- `backend/scripts/mark_existing_users_for_email_linking.py` ✅
- `backend/scripts/verify_migration.py` ✅
- `backend/scripts/cleanup_orphaned_sessions.py` ✅

---

## Support

**Questions or issues?**
1. Check this guide first
2. Check backend logs: `tail -f backend/backend.log`
3. Run verification: `python backend/scripts/verify_migration.py`
4. Check database: `psql` and run diagnostic queries above

**Emergency rollback:**
```bash
psql -f backend/migrations/001_rollback.sql && git revert HEAD~3 && npm run dev
```
