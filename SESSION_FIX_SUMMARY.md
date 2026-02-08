# Session Fix Summary — Phase 27

## Issues Identified

### Issue 1: UUID Type Error ❌
**Error**: `'asyncpg.pgproto.pgproto.UUID' object has no attribute 'replace'`

**Root Cause**:
- asyncpg returns `auth_user_id` column as `asyncpg.pgproto.pgproto.UUID` object
- Supabase client's `admin.get_user_by_id()` expects a string UUID
- Logger was trying to format UUID object, causing AttributeError

**Location**: `backend/app/routes/email_linking.py` line 53

### Issue 2: Telegram Session Not Found After Email Login ❌
**Error**: `텔레그램 세션을 찾을 수 없습니다. 다시 로그인해주세요. (status=401)`

**Root Cause**:
- After email linking, session was moved from `telethon_sessions` to `telegram_connections`
- Silent failure in `link_telegram_to_auth_user()` due to `ON CONFLICT DO NOTHING`
- No verification that the INSERT succeeded

**Location**: `backend/app/supabase_auth.py` line 110-119

## Fixes Applied

### Fix 1: UUID String Conversion (3 locations)

#### email_linking.py:53
```python
# Before
auth_user = await supabase_auth_manager.client.auth.admin.get_user_by_id(auth_user_id)

# After
auth_user = await supabase_auth_manager.client.auth.admin.get_user_by_id(str(auth_user_id))
```

#### email_linking.py:59
```python
# Before
logger.warning("Failed to get auth user %s: %s", auth_user_id, e)

# After
logger.warning("Failed to get auth user %s: %s", str(auth_user_id), e)
```

#### email_linking.py:196
```python
# Before
linked = await supabase_auth_manager.link_telegram_to_auth_user(
    auth_user_id=auth_user_id,
    ...
)

# After
linked = await supabase_auth_manager.link_telegram_to_auth_user(
    auth_user_id=str(auth_user_id),
    ...
)
```

### Fix 2: Improved Session Linking Logic

#### supabase_auth.py:link_telegram_to_auth_user()

**Changes:**
1. Check if entry exists BEFORE inserting (avoid `DO NOTHING`)
2. If exists, UPDATE instead of ignoring
3. Verify the entry after INSERT/UPDATE
4. Return `False` if verification fails
5. Better error logging with all parameters

**Before:**
```python
await db.execute(
    """INSERT INTO telegram_connections ...
       ON CONFLICT (telegram_user_id) DO NOTHING""",
    ...
)
return True  # Always returns True even if DO NOTHING triggered
```

**After:**
```python
existing = await db.fetchrow(
    "SELECT id FROM telegram_connections WHERE telegram_user_id = $1",
    telegram_user_id
)

if existing:
    await db.execute("UPDATE telegram_connections SET ... WHERE telegram_user_id = $1", ...)
else:
    await db.execute("INSERT INTO telegram_connections ...", ...)

# Verify
verify = await db.fetchrow("SELECT user_id, auth_user_id FROM telegram_connections WHERE telegram_user_id = $1", ...)
if not verify:
    return False

return True
```

### Fix 3: Error Handling & Logging

#### email_linking.py:208-217
- Changed `logger.warning` → `logger.error` for failed session linking
- Raise HTTPException 500 instead of silently continuing
- Added success logging with all IDs

#### auth.py:login-email
- Added diagnostic logging of session status (telegram_connections vs telethon_sessions counts)
- Better error messages when user not found

## Testing

### Test Case 1: Fresh Email Signup (No Telegram)
✅ Should work — creates Supabase Auth user only

### Test Case 2: Telegram → Email Linking Flow
1. Login via Telegram ✅
2. Link email via `/link-email` ✅ (should create telegram_connections entry)
3. Logout
4. Login via email ✅ (should find session in telegram_connections)
5. Access `/my-telegram-groups` ✅ (should work with linked session)

### Test Case 3: Existing User Re-Link
- If telegram_connections entry already exists, UPDATE instead of ignoring

## Diagnostic Tools

### Script: `backend/scripts/diagnose_session.py`
```bash
# By user ID
python backend/scripts/diagnose_session.py 4

# By email
python backend/scripts/diagnose_session.py --email song52114@gmail.com
```

**Output:**
- User record details
- telegram_connections entries (count, key_hash, session length)
- telethon_sessions entries (count, key_hash, session length)
- Recommendations based on state

## Files Modified

1. `backend/app/routes/email_linking.py` — UUID conversion, error handling
2. `backend/app/supabase_auth.py` — Session linking logic, verification
3. `backend/app/routes/auth.py` — Diagnostic logging
4. `backend/scripts/diagnose_session.py` — NEW diagnostic tool

## Migration Path (If Needed)

If users are stuck with no telegram_connections entry:

```sql
-- Manual migration for stuck users
INSERT INTO telegram_connections (
    user_id, auth_user_id, telegram_user_id,
    session_encrypted, key_hash, phone_masked, username
)
SELECT
    u.id, u.auth_user_id, u.telegram_id,
    ts.session_data, ts.key_hash,
    CONCAT('+', SUBSTRING(u.phone_number, 1, 3), '****', RIGHT(u.phone_number, 4)),
    u.username
FROM users u
INNER JOIN telethon_sessions ts ON ts.user_id = u.id
WHERE u.auth_user_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM telegram_connections tc
      WHERE tc.telegram_user_id = u.telegram_id
  );
```

## Next Steps

1. ✅ Restart backend server
2. ✅ Test email login flow
3. ✅ Check logs for UUID errors (should be gone)
4. ✅ Use diagnostic script on affected users
5. ⏸️ If issues persist, run migration SQL above
