# 🚀 AaltoHub v2 - Quick Start Guide

## 📍 Current Status
✅ **All systems operational and ready for testing**

## 🎯 Access the Application

### Frontend
```
http://localhost:3000
```
**Expected behavior:** Auto-redirects to login page if not authenticated

### Backend API
```
http://63.180.156.219:8000
http://63.180.156.219:8000/docs  (API documentation with Swagger UI)
http://63.180.156.219:8000/health (health check)
```

---

## 🔐 Test the Telegram Login

### Step 1: Navigate to Login
```
Open: http://localhost:3000/login
```

### Step 2: Enter Telegram Credentials
You have two options:
- **Option A:** Enter a phone number (e.g., `+358449598622`)
- **Option B:** Enter a username (e.g., `@chaeyeonsally`)

### Step 3: Get Verification Code
- Click "인증 코드 받기" (Get Verification Code)
- Check your Telegram app for the 5-digit code
- Copy the code and paste it in the login form

### Step 4: Complete Login
- Enter the code
- If 2FA is enabled, you'll be asked for your password
- On success, you'll be redirected to:
  - `/groups` (if regular user)
  - `/admin` (if admin user)

---

## 📱 Test Each Feature

### User Features
1. **View Groups**
   - Go to `/groups` after login
   - See all your registered Telegram groups
   - Click "그룹 추가" (Add Group) to register more groups

2. **Register Groups**
   - Click "그룹 추가" button
   - Select groups you want to register
   - Choose visibility (Public/Private)
   - Click "등록" (Register)

3. **View Group Details**
   - Click on a group in the list
   - See group information and settings
   - Configure group-specific settings

### Admin Features
1. **Admin Dashboard**
   - Login as admin user
   - See all registered groups
   - View group statistics
   - Browse message history

2. **Crawler Management**
   - Go to `/admin/crawler`
   - Control message crawling for groups
   - View crawling status and statistics

3. **Failed Invites**
   - Check admin invitations to groups
   - Retry failed invitations

---

## 🔧 Monitor Services

### Check Backend Status
```bash
curl http://63.180.156.219:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "environment": "development"
}
```

### View Backend Logs
```bash
ssh -i telegram-crawler-key.pem ubuntu@63.180.156.219
tail -f /tmp/backend.log
```

### Check Frontend Console
Open browser DevTools (F12) → Console tab to see any errors

---

## 🛠️ Troubleshooting

### Issue: Login page doesn't load
**Solution:**
1. Check frontend is running: `ps aux | grep vite`
2. Check API connection: `curl http://63.180.156.219:8000/health`
3. Clear browser cache (Ctrl+Shift+Delete)
4. Check browser console for errors

### Issue: "Cannot send code" error
**Solution:**
1. Verify Telegram API credentials in `.env`
2. Check backend logs: `tail -f /tmp/backend.log`
3. Ensure valid phone number format: `+358...`
4. Verify Telethon library is installed: `python -m pip list | grep telethon`

### Issue: "2FA required" but wrong password
**Solution:**
1. Verify Telegram 2FA password (not your regular password)
2. Check Telegram app Settings → Privacy → Two-Step Verification
3. Reset 2FA if forgotten

### Issue: CORS errors in console
**Solution:**
1. Backend CORS is configured for `localhost:3000`
2. Check API URL in `.env.local`: `VITE_API_URL=http://63.180.156.219:8000`
3. Restart frontend: `pkill -f vite && pnpm dev`

---

## 📊 API Examples

### Send Code
```bash
curl -X POST http://63.180.156.219:8000/api/auth/send-code \
  -H "Content-Type: application/json" \
  -d '{"phone_or_username": "+358449598622"}'
```

### Verify Code
```bash
curl -X POST http://63.180.156.219:8000/api/auth/verify-code \
  -H "Content-Type: application/json" \
  -d '{
    "phone_or_username": "+358449598622",
    "code": "12345",
    "phone_code_hash": "hash_from_send_code"
  }'
```

### Get Current User (with token)
```bash
curl -X GET http://63.180.156.219:8000/api/auth/me \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

### Get User's Groups (with token)
```bash
curl -X GET http://63.180.156.219:8000/api/groups/my-telegram-groups \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

---

## 📚 Documentation Files

- **IMPLEMENTATION_STATUS.md** - Detailed feature list and setup guide
- **CREDENTIALS_SETUP.md** - How to manage credentials securely
- **RALPH_LOOP_COMPLETE.md** - Full audit and optimization report
- **SETUP_SUMMARY.md** - Initial setup overview

---

## 🎓 Architecture Overview

```
Frontend (React)
     ↓
API Client (Axios)
     ↓
Backend (FastAPI)
     ↓
Supabase (PostgreSQL)
     ↓
Telegram API (Telethon)
```

### Data Flow
1. User enters phone/username on login page
2. Frontend sends to `/api/auth/send-code`
3. Backend creates Telethon client and sends code via Telegram
4. User receives code in Telegram app
5. User enters code on login page
6. Frontend sends to `/api/auth/verify-code`
7. Backend signs in with Telethon and saves encrypted session
8. Backend returns JWT tokens
9. Frontend stores tokens and redirects to `/groups` or `/admin`

---

## 🔐 Security Notes

- ✅ Sessions are encrypted with AES before storage
- ✅ JWT tokens are signed and expire after 60 minutes (access) or 30 days (refresh)
- ✅ Admin-only endpoints require `role === 'admin'`
- ✅ Protected routes redirect unauthenticated users to login
- ✅ CORS is configured to only accept requests from localhost:3000
- ✅ Credentials are stored in `.env.local` (never committed to git)

---

## 🚀 Next Steps

1. **Test Core Features**
   - [ ] Login with Telegram account
   - [ ] Verify 2FA (if enabled)
   - [ ] Register groups
   - [ ] View group details

2. **Test Admin Features**
   - [ ] Access admin dashboard
   - [ ] View group statistics
   - [ ] Manage crawlers
   - [ ] Check failed invites

3. **Test Edge Cases**
   - [ ] Logout and re-login
   - [ ] Invalid code entry
   - [ ] Network disconnection handling
   - [ ] Browser back/forward navigation

4. **Performance & UX**
   - [ ] Check load times
   - [ ] Test on mobile device
   - [ ] Verify error messages
   - [ ] Check dark/light mode toggle

---

## 📞 Getting Help

1. Check browser console (F12 → Console)
2. Check backend logs: `tail -f /tmp/backend.log`
3. Check API docs: http://63.180.156.219:8000/docs
4. Review documentation files in project root
5. Check GitHub repository: https://github.com/sallysong51/aaltohubv2

---

**Happy testing! 🎉**

For more detailed information, see the other documentation files in the project root.
