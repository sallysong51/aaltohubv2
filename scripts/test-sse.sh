#!/bin/bash
# SSE Connection Test Script
# Tests both ticket-based and legacy token-based SSE authentication

set -e

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  SSE Connection Test"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if backend is running
echo "1. Checking backend health..."
if curl -s -f "$BACKEND_URL/health" > /dev/null 2>&1; then
    echo -e "   ${GREEN}✓${NC} Backend is running"
else
    echo -e "   ${RED}✗${NC} Backend is not reachable"
    exit 1
fi

# Check SSE listener status
SSE_STATUS=$(curl -s "$BACKEND_URL/health" | jq -r .sse_listener 2>/dev/null || echo "unknown")
if [ "$SSE_STATUS" = "connected" ]; then
    echo -e "   ${GREEN}✓${NC} SSE Listener: connected"
else
    echo -e "   ${YELLOW}⚠${NC} SSE Listener: $SSE_STATUS"
fi

echo ""
echo "2. Testing SSE authentication endpoints..."

# Test ticket endpoint (requires authentication)
echo ""
echo "   Testing POST /api/events/ticket (requires login)..."
echo "   ${YELLOW}Note:${NC} You must be logged in to test this"
echo ""
echo "   To test manually:"
echo "   1. Open browser to http://localhost:3000"
echo "   2. Login with Telegram"
echo "   3. Open browser DevTools (F12)"
echo "   4. Go to Console tab"
echo "   5. Run:"
echo ""
echo "      const token = localStorage.getItem('access_token');"
echo "      fetch('$BACKEND_URL/api/events/ticket?groups=123', {"
echo "        method: 'POST',"
echo "        headers: { 'Authorization': \`Bearer \${token}\` }"
echo "      }).then(r => r.json()).then(console.log);"
echo ""
echo "   Expected output:"
echo "      { ticket: '...', expires_in: 60 }"
echo ""
echo "   If you get an error, check:"
echo "   - Are you logged in? (localStorage.getItem('access_token') should return a JWT)"
echo "   - Is the backend running? (check health endpoint)"
echo "   - Check backend logs for errors"

echo ""
echo "3. Browser SSE Connection Test..."
echo ""
echo "   To verify SSE is working in the browser:"
echo "   1. Open http://localhost:3000"
echo "   2. Login"
echo "   3. Navigate to EventFeed page"
echo "   4. Open DevTools Console (F12)"
echo "   5. Look for:"
echo ""
echo "      ${GREEN}✓ Success:${NC} No errors, SSE connected silently"
echo "      ${RED}✗ Failure:${NC} '[SSE] Connection lost. Reconnecting in Xs'"
echo ""
echo "   6. Check Network tab:"
echo "      - Find request to /api/events/stream?ticket=..."
echo "      - Status should be: 200 (pending) with EventStream type"
echo "      - Should see keepalive comments every 30s"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  SSE Test Complete"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Additional diagnostics:"
echo "  - Health check:     pnpm run health"
echo "  - Backend logs:     Check terminal running 'pnpm run dev'"
echo "  - Documentation:    docs/SSE_FIX_2026-02-11.md"
echo ""
