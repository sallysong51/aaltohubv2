# AaltoHub v2 Troubleshooting Guide

## Quick Health Check

```bash
# One-time health check
pnpm run health

# Continuous monitoring (updates every 5s)
pnpm run health:watch
```

## Common Issues

### 1. Vite Proxy Error: `/health` or `/api/*`

**Symptom:**
```
[vite] http proxy error: /health
```

**Root Cause:**
- Backend server not running or not ready yet
- Port conflict
- Network connectivity issue

**Solutions:**

1. **Check if backend is running:**
   ```bash
   pnpm run health
   # Look for: ✓ Backend API - PID: XXXXX
   ```

2. **Restart all services:**
   ```bash
   pnpm run dev
   # Or for auto-restart on crash:
   pnpm run dev:resilient
   ```

3. **Manual port check:**
   ```bash
   # Check if ports are in use
   lsof -i :3000 -i :8000 -i :8001

   # Kill stale processes
   pnpm run kill-ports
   ```

4. **Test backend directly:**
   ```bash
   # Should return JSON health status
   curl http://localhost:8000/health
   ```

5. **Test vite proxy:**
   ```bash
   # Should proxy to backend successfully
   curl http://localhost:3000/health
   ```

### 2. Database Connection Errors

**Symptom:**
```
Database: false
SSE Listener: disconnected
```

**Solutions:**

1. **Check DATABASE_URL in backend/.env:**
   ```bash
   # Must use Session Pooler (port 5432), NOT Transaction Pooler (port 6543)
   DATABASE_URL=postgresql://postgres.XXX:PASSWORD@aws-X-region.pooler.supabase.com:5432/postgres
   ```

2. **Test database connectivity:**
   ```bash
   cd backend
   source venv/bin/activate
   python scripts/preflight.py
   ```

3. **Check Supabase project status:**
   - Visit https://supabase.com/dashboard
   - Verify project is active and not paused

### 3. Frontend Shows "Backend Unreachable"

**Symptom:**
- Red banner in UI: "백엔드 서버가 응답하지 않습니다"
- 503 errors in console

**Solutions:**

1. **Run health check:**
   ```bash
   pnpm run health
   ```

2. **Check backend logs:**
   ```bash
   # Look for errors in the terminal running pnpm run dev
   # Backend logs are prefixed with [backend]
   ```

3. **Verify environment variables:**
   ```bash
   cd backend
   cat .env | grep -E "(DATABASE_URL|SUPABASE_URL|JWT_SECRET|TELEGRAM_API_ID)"
   ```

### 4. SSE (Server-Sent Events) Not Working

**Symptom A: Connection fails with 400 Bad Request**
```
GET http://localhost:8000/api/events/stream?ticket=... 400 (Bad Request)
[SSE] Connection lost. Reconnecting in 4s
```

**Root Cause:**
- Backend code bug (fixed in commit 7f67fef8)
- group_ids parameter handling issue in ticket-based auth

**Solution:**
1. **Pull latest code:**
   ```bash
   git pull origin main
   # Should include commit: "fix(sse): Fix 400 error in ticket-based SSE authentication"
   ```

2. **Restart backend:**
   ```bash
   pnpm run kill-ports
   pnpm run dev
   ```

3. **Verify fix:**
   ```bash
   ./scripts/test-sse.sh
   ```

4. **Check browser console:**
   - Should NOT see reconnection loops
   - Network tab shows: `GET /api/events/stream?ticket=...` with status 200 (pending)

**Symptom B: SSE not configured**
- Console shows: "SSE not configured"
- No real-time updates in EventFeed

**Solutions:**

1. **Check SSE_BASE_URL in client/.env:**
   ```bash
   cat client/.env
   # Should have:
   VITE_SSE_URL=http://localhost:8000
   ```

2. **Test SSE endpoint:**
   ```bash
   curl -N http://localhost:8000/api/events/stream
   # Should keep connection open
   ```

3. **Check SSE listener status:**
   ```bash
   curl http://localhost:8000/health | jq .sse_listener
   # Should return: "connected"
   ```

### 5. Services Won't Start

**Symptom:**
```
Error: Address already in use
```

**Solutions:**

1. **Kill all ports and restart:**
   ```bash
   pnpm run kill-ports
   pnpm run dev
   ```

2. **Manual process check:**
   ```bash
   # Find what's using ports
   lsof -i :3000
   lsof -i :8000
   lsof -i :8001

   # Kill specific PID
   kill -9 <PID>
   ```

### 6. Crawler Not Crawling

**Symptom:**
- Crawler status shows "initializing" or "error"
- No messages appearing in database

**Solutions:**

1. **Check crawler health:**
   ```bash
   curl http://localhost:8001/health
   ```

2. **Check crawler logs:**
   ```bash
   # Look for [crawler] prefix in terminal
   # Common issues:
   # - Telegram session errors
   # - FloodWait penalties
   # - Database connection issues
   ```

3. **Verify Telegram credentials:**
   ```bash
   cd backend
   cat .env | grep TELEGRAM
   # Should have:
   TELEGRAM_API_ID=...
   TELEGRAM_API_HASH=...
   ```

4. **Check admin authentication:**
   ```bash
   # Verify admin phone is correct
   cat backend/.env | grep ADMIN_PHONE
   ```

## Service Architecture

```
┌─────────────────────────────────────────────────────┐
│  Browser (localhost:3000)                           │
│  ┌──────────────────────────────────────────┐       │
│  │  Frontend (React + Vite)                 │       │
│  │  - Event Feed                            │       │
│  │  - Admin Dashboard                       │       │
│  └──────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────┘
         │                        │
         │ HTTP API              │ SSE (EventSource)
         │ (Vite Proxy)          │ (Direct)
         ↓                        ↓
┌─────────────────────────────────────────────────────┐
│  Backend API (localhost:8000)                       │
│  ┌──────────────────────────────────────────┐       │
│  │  FastAPI + asyncpg                       │       │
│  │  - Auth (/api/auth/*)                    │       │
│  │  - Groups (/api/groups/*)                │       │
│  │  - Events (/api/events/stream) - SSE     │       │
│  │  - Health (/health)                      │       │
│  └──────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────┘
         │                        ↑
         │ DB Queries             │ pg_notify
         ↓                        │
┌─────────────────────────────────────────────────────┐
│  Supabase Postgres                                  │
│  - Session Pooler (port 5432)                       │
│  - LISTEN/NOTIFY for SSE                            │
└─────────────────────────────────────────────────────┘
         ↑
         │ INSERT messages
         │
┌─────────────────────────────────────────────────────┐
│  Crawler (localhost:8001)                           │
│  ┌──────────────────────────────────────────┐       │
│  │  Telethon + Live Event Listeners         │       │
│  │  - NewMessage, MessageEdited, etc        │       │
│  │  - Historical crawl                      │       │
│  │  - Gap-fill                              │       │
│  └──────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────┘
         ↑
         │ Telegram MTProto
         │
┌─────────────────────────────────────────────────────┐
│  Telegram Servers                                   │
└─────────────────────────────────────────────────────┘
```

## Monitoring Commands

```bash
# Quick health snapshot
pnpm run health

# Continuous monitoring (Ctrl+C to stop)
pnpm run health:watch

# Check specific service
curl http://localhost:8000/health | jq .
curl http://localhost:8001/health | jq .

# Check database connectivity
cd backend && source venv/bin/activate && python scripts/preflight.py

# View Prometheus metrics
curl http://localhost:8000/metrics
```

## When to Restart Services

**Always restart after:**
- Changing environment variables (.env files)
- Installing new Python packages (backend/requirements.txt)
- Installing new npm packages (package.json)
- Modifying database schema

**Soft restart (keep data):**
```bash
pnpm run kill-ports
pnpm run dev
```

**Hard restart (clear caches):**
```bash
# Kill processes
pnpm run kill-ports

# Clear Python cache
cd backend
find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete

# Clear npm cache (rarely needed)
pnpm store prune

# Restart
pnpm run dev
```

## Getting Help

1. **Check logs first:**
   - Terminal running `pnpm run dev` shows all service logs
   - Look for [backend], [crawler], [frontend] prefixes

2. **Run health check:**
   ```bash
   pnpm run health
   ```

3. **Check this guide:**
   - Search for your error message above

4. **Report issue:**
   - Include health check output
   - Include relevant logs from terminal
   - Include steps to reproduce

## Emergency Recovery

**If nothing works:**

1. **Nuclear reset:**
   ```bash
   # Kill everything
   pnpm run kill-ports

   # Clear all caches
   cd backend
   find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
   rm -rf venv
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   cd ..

   # Reinstall frontend deps
   pnpm install

   # Restart
   pnpm run dev
   ```

2. **Database reset (⚠️ LOSES ALL DATA):**
   ```bash
   # Run rollback migrations
   cd backend
   # ... execute rollback SQL from migrations/

   # Run fresh migrations
   # ... execute migration SQL from migrations/
   ```

3. **Telegram session reset:**
   ```bash
   # If authentication is broken, delete session and re-login
   cd backend
   rm -f telegram_sessions/*.session
   # Next startup will prompt for Telegram auth again
   ```
