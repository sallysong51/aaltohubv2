#!/usr/bin/env bash
# health_check.sh -- AaltoHub v2 health check with alerting
#
# Checks the /health endpoint and sends an alert via webhook if unhealthy.
# Designed to be called by cron every 5 minutes:
#   */5 * * * * /path/to/scripts/health_check.sh >> /var/log/aaltohub-health.log 2>&1
#
# Environment variables:
#   HEALTH_URL          Base URL for the health endpoint (default: http://localhost:8000/health)
#   ALERT_WEBHOOK_URL   Webhook URL to POST alerts to (Slack, Discord, PagerDuty, etc.)
#   HEALTH_TIMEOUT      Curl timeout in seconds (default: 10)

set -euo pipefail

HEALTH_URL="${HEALTH_URL:-http://localhost:8000/health}"
ALERT_WEBHOOK_URL="${ALERT_WEBHOOK_URL:-}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-10}"
TIMESTAMP="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

log() {
    echo "[${TIMESTAMP}] $1"
}

send_alert() {
    local message="$1"
    if [ -z "${ALERT_WEBHOOK_URL}" ]; then
        log "WARN: ALERT_WEBHOOK_URL not set -- skipping webhook alert"
        return 0
    fi
    curl -s -X POST "${ALERT_WEBHOOK_URL}" \
        -H "Content-Type: application/json" \
        -d "{\"text\": \"${message}\", \"username\": \"AaltoHub Health Check\"}" \
        --max-time 10 \
        > /dev/null 2>&1 || log "WARN: Failed to send alert to webhook"
}

# Fetch health endpoint
HTTP_CODE=0
RESPONSE=""
RESPONSE=$(curl -s -w "\n%{http_code}" --max-time "${HEALTH_TIMEOUT}" "${HEALTH_URL}" 2>&1) || true

if [ -z "${RESPONSE}" ]; then
    log "CRITICAL: Health endpoint unreachable at ${HEALTH_URL}"
    send_alert "[CRITICAL] AaltoHub health endpoint unreachable at ${HEALTH_URL} (${TIMESTAMP})"
    exit 1
fi

# Split response body and HTTP status code
HTTP_CODE=$(echo "${RESPONSE}" | tail -n1)
BODY=$(echo "${RESPONSE}" | sed '$d')

# Check HTTP status
if [ "${HTTP_CODE}" != "200" ]; then
    log "UNHEALTHY: HTTP ${HTTP_CODE} -- ${BODY}"
    send_alert "[ALERT] AaltoHub unhealthy (HTTP ${HTTP_CODE}): ${BODY} (${TIMESTAMP})"
    exit 1
fi

# Parse status field from JSON response
STATUS=$(echo "${BODY}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "parse_error")

if [ "${STATUS}" != "healthy" ]; then
    log "DEGRADED: status=${STATUS} -- ${BODY}"
    send_alert "[ALERT] AaltoHub degraded (status=${STATUS}): ${BODY} (${TIMESTAMP})"
    exit 1
fi

log "OK: status=healthy"
exit 0
