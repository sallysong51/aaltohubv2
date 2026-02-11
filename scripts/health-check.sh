#!/bin/bash
# AaltoHub v2 Health Check Script
# Usage: ./scripts/health-check.sh [--continuous]

set -e

FRONTEND_URL="http://localhost:3000"
BACKEND_URL="http://localhost:8000"
CRAWLER_URL="http://localhost:8001"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

check_service() {
    local name=$1
    local url=$2
    local endpoint=$3

    if curl -s -f -m 5 "${url}${endpoint}" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} $name: ${GREEN}healthy${NC}"
        return 0
    else
        echo -e "${RED}✗${NC} $name: ${RED}unreachable${NC}"
        return 1
    fi
}

check_detailed_health() {
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  AaltoHub v2 Health Check - $(date '+%Y-%m-%d %H:%M:%S')"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Check processes
    echo "🔍 Process Status:"
    if pgrep -f "vite.*--host" > /dev/null; then
        echo -e "  ${GREEN}✓${NC} Frontend (Vite) - PID: $(pgrep -f 'vite.*--host')"
    else
        echo -e "  ${RED}✗${NC} Frontend (Vite) - Not running"
    fi

    if pgrep -f "uvicorn.*app.main:app" > /dev/null; then
        echo -e "  ${GREEN}✓${NC} Backend API - PID: $(pgrep -f 'uvicorn.*app.main:app')"
    else
        echo -e "  ${RED}✗${NC} Backend API - Not running"
    fi

    if pgrep -f "uvicorn.*crawler_main:app" > /dev/null; then
        echo -e "  ${GREEN}✓${NC} Crawler - PID: $(pgrep -f 'uvicorn.*crawler_main:app')"
    else
        echo -e "  ${RED}✗${NC} Crawler - Not running"
    fi

    echo ""
    echo "🌐 HTTP Endpoint Status:"

    # Check frontend
    check_service "Frontend (direct)" "$FRONTEND_URL" "/"

    # Check backend health
    if check_service "Backend /health" "$BACKEND_URL" "/health"; then
        # Get detailed health info
        health_json=$(curl -s "$BACKEND_URL/health")
        echo "  Database: $(echo $health_json | jq -r .database_connected)"
        echo "  SSE Listener: $(echo $health_json | jq -r .sse_listener)"
        echo "  Queue: $(echo $health_json | jq -r .queue_healthy)"
        echo "  Crawler: $(echo $health_json | jq -r .crawler.status)"
    fi

    # Check vite proxy
    if curl -s -f -m 5 "$FRONTEND_URL/health" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Vite Proxy (/health): ${GREEN}working${NC}"
    else
        echo -e "${RED}✗${NC} Vite Proxy (/health): ${RED}not working${NC}"
    fi

    echo ""
    echo "📡 Port Status:"
    echo "  Port 3000 (Frontend): $(lsof -i :3000 -sTCP:LISTEN -t | wc -l | tr -d ' ') listener(s)"
    echo "  Port 8000 (Backend):  $(lsof -i :8000 -sTCP:LISTEN -t | wc -l | tr -d ' ') listener(s)"
    echo "  Port 8001 (Crawler):  $(lsof -i :8001 -sTCP:LISTEN -t | wc -l | tr -d ' ') listener(s)"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Main execution
if [ "$1" = "--continuous" ] || [ "$1" = "-c" ]; then
    echo "Starting continuous health monitoring (press Ctrl+C to stop)..."
    while true; do
        clear
        check_detailed_health
        sleep 5
    done
else
    check_detailed_health
fi
