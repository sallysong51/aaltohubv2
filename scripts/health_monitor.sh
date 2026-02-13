#!/usr/bin/env bash
# health_monitor.sh -- AaltoHub v2 automated recovery and monitoring
#
# Monitors system health and automatically restarts services when unhealthy.
# Designed to run via cron every 5 minutes:
#   */5 * * * * /home/ubuntu/AALTOHUBv2/scripts/health_monitor.sh
#
# Features:
#   - Health checks for Crawler and API services
#   - Automatic service restart on failure
#   - Disk and memory monitoring
#   - Automatic log cleanup
#   - Multi-layer alerting (Sentry + optional AWS SNS)
#
# Requirements:
#   - sudo privileges for systemctl restart (configure sudoers)
#   - AWS CLI configured (optional, for SNS alerts)
#   - Sentry DSN configured (reads from .env)

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

# Service URLs
CRAWLER_URL="${CRAWLER_URL:-http://localhost:8001/health}"
API_URL="${API_URL:-http://localhost:8000/health}"

# Timeouts
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-10}"
RESTART_WAIT="${RESTART_WAIT:-10}"

# Resource thresholds
DISK_WARN_THRESHOLD="${DISK_WARN_THRESHOLD:-85}"  # percent
MEM_WARN_THRESHOLD="${MEM_WARN_THRESHOLD:-256}"   # MB available

# Paths
PROJECT_ROOT="/home/ubuntu/AALTOHUBv2"
LOG_DIR="${PROJECT_ROOT}/logs"
MONITOR_LOG="${LOG_DIR}/monitor.log"
ENV_FILE="${PROJECT_ROOT}/backend/.env"

# AWS SNS (optional)
SNS_TOPIC_ARN="${SNS_TOPIC_ARN:-}"  # Set via environment or cron

# Sentry (optional, for critical alerts)
SENTRY_DSN=""
if [ -f "${ENV_FILE}" ]; then
    SENTRY_DSN=$(grep '^SENTRY_DSN=' "${ENV_FILE}" 2>/dev/null | cut -d'=' -f2- | tr -d '"' || true)
fi

# ============================================================================
# Helper Functions
# ============================================================================

timestamp() {
    date +'%Y-%m-%d %H:%M:%S'
}

log_info() {
    echo "[$(timestamp)] [INFO] $1" | tee -a "${MONITOR_LOG}"
}

log_warn() {
    echo "[$(timestamp)] [WARN] $1" | tee -a "${MONITOR_LOG}"
}

log_error() {
    echo "[$(timestamp)] [ERROR] $1" | tee -a "${MONITOR_LOG}"
}

log_critical() {
    echo "[$(timestamp)] [CRITICAL] $1" | tee -a "${MONITOR_LOG}"
}

# Send Sentry alert for critical issues
send_sentry_alert() {
    local message="$1"
    local level="${2:-error}"  # error, warning, info

    if [ -z "${SENTRY_DSN}" ]; then
        return 0
    fi

    # Simple Sentry capture using curl (no SDK needed)
    # Format: https://sentry.io/api/PROJECT_ID/store/
    local sentry_url=$(echo "${SENTRY_DSN}" | sed -E 's|https://([^@]+)@([^/]+)/(.+)|https://\2/api/\3/store/|')
    local sentry_key=$(echo "${SENTRY_DSN}" | sed -E 's|https://([^:]+).*|\1|')

    curl -s -X POST "${sentry_url}" \
        -H "X-Sentry-Auth: Sentry sentry_key=${sentry_key}, sentry_version=7" \
        -H "Content-Type: application/json" \
        -d "{
            \"message\": \"${message}\",
            \"level\": \"${level}\",
            \"tags\": {\"source\": \"health_monitor\"},
            \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
        }" \
        --max-time 5 > /dev/null 2>&1 || true
}

# Send AWS SNS alert (optional)
send_sns_alert() {
    local subject="$1"
    local message="$2"

    if [ -z "${SNS_TOPIC_ARN}" ]; then
        return 0
    fi

    if ! command -v aws &> /dev/null; then
        log_warn "AWS CLI not installed, skipping SNS alert"
        return 0
    fi

    aws sns publish \
        --topic-arn "${SNS_TOPIC_ARN}" \
        --subject "${subject}" \
        --message "${message}" \
        > /dev/null 2>&1 || log_warn "Failed to send SNS alert"
}

# Check HTTP health endpoint
check_health() {
    local name="$1"
    local url="$2"

    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "${HEALTH_TIMEOUT}" "${url}" 2>/dev/null || echo "000")

    if [ "${http_code}" = "200" ]; then
        return 0
    else
        log_error "${name} unhealthy (HTTP ${http_code})"
        return 1
    fi
}

# Restart systemd service
restart_service() {
    local service_name="$1"

    log_info "Attempting to restart ${service_name}..."

    if sudo systemctl restart "${service_name}"; then
        log_info "${service_name} restarted successfully"
        sleep "${RESTART_WAIT}"
        return 0
    else
        log_critical "${service_name} restart FAILED"
        return 1
    fi
}

# ============================================================================
# Main Health Checks
# ============================================================================

# Ensure log directory exists
mkdir -p "${LOG_DIR}"

# Check Crawler service
if ! check_health "Crawler" "${CRAWLER_URL}"; then
    log_warn "Crawler unhealthy, restarting aaltohub-crawler service..."

    if restart_service "aaltohub-crawler"; then
        # Re-check after restart
        if check_health "Crawler" "${CRAWLER_URL}"; then
            log_info "Crawler recovered successfully after restart"
            send_sentry_alert "Crawler service restarted successfully" "warning"
        else
            log_critical "Crawler still unhealthy after restart!"
            send_sentry_alert "Crawler DOWN after restart attempt" "error"
            send_sns_alert "CRITICAL: AaltoHub Crawler Down" \
                "Crawler service failed to recover after restart.\nTime: $(timestamp)\nAction: Manual intervention required."
        fi
    else
        log_critical "Failed to restart Crawler service"
        send_sentry_alert "Crawler service restart failed" "error"
        send_sns_alert "CRITICAL: Crawler Restart Failed" \
            "Unable to restart aaltohub-crawler service.\nTime: $(timestamp)\nAction: Check systemd logs with 'journalctl -u aaltohub-crawler -n 50'"
    fi
fi

# Check API service
if ! check_health "API" "${API_URL}"; then
    log_warn "API unhealthy, restarting aaltohub-api service..."

    if restart_service "aaltohub-api"; then
        # Re-check after restart
        if check_health "API" "${API_URL}"; then
            log_info "API recovered successfully after restart"
            send_sentry_alert "API service restarted successfully" "warning"
        else
            log_critical "API still unhealthy after restart!"
            send_sentry_alert "API DOWN after restart attempt" "error"
            send_sns_alert "CRITICAL: AaltoHub API Down" \
                "API service failed to recover after restart.\nTime: $(timestamp)\nAction: Manual intervention required."
        fi
    else
        log_critical "Failed to restart API service"
        send_sentry_alert "API service restart failed" "error"
    fi
fi

# ============================================================================
# Resource Monitoring
# ============================================================================

# Disk usage check
DISK_USAGE=$(df "${PROJECT_ROOT}" --output=pcent 2>/dev/null | tail -1 | tr -d ' %' || echo "0")

if [ "${DISK_USAGE}" -gt "${DISK_WARN_THRESHOLD}" ]; then
    log_warn "Disk usage at ${DISK_USAGE}% (threshold: ${DISK_WARN_THRESHOLD}%)"

    # Clean up old journalctl logs
    log_info "Cleaning up journalctl logs (keeping last 7 days)..."
    sudo journalctl --vacuum-time=7d > /dev/null 2>&1 || log_warn "journalctl cleanup failed"

    # Clean up old monitor logs
    log_info "Cleaning up old monitor logs (keeping last 7 days)..."
    find "${LOG_DIR}" -name "*.log" -mtime +7 -delete 2>/dev/null || log_warn "log cleanup failed"

    # Re-check disk usage
    DISK_USAGE_AFTER=$(df "${PROJECT_ROOT}" --output=pcent 2>/dev/null | tail -1 | tr -d ' %' || echo "0")
    log_info "Disk usage after cleanup: ${DISK_USAGE_AFTER}%"

    if [ "${DISK_USAGE_AFTER}" -gt "${DISK_WARN_THRESHOLD}" ]; then
        log_warn "Disk usage still high after cleanup (${DISK_USAGE_AFTER}%)"
        send_sentry_alert "Disk usage critically high: ${DISK_USAGE_AFTER}%" "warning"
    fi
fi

# Memory check
if command -v free &> /dev/null; then
    MEM_AVAIL=$(free -m | awk '/Mem:/ {print $7}' || echo "999999")

    if [ "${MEM_AVAIL}" -lt "${MEM_WARN_THRESHOLD}" ]; then
        log_warn "Low memory: ${MEM_AVAIL}MB available (threshold: ${MEM_WARN_THRESHOLD}MB)"
        send_sentry_alert "Low memory: ${MEM_AVAIL}MB available" "warning"
    fi
fi

# ============================================================================
# Summary
# ============================================================================

log_info "Health monitor completed successfully"
