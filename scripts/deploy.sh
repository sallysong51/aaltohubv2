#!/usr/bin/env bash
# deploy.sh -- Zero-downtime deployment for AaltoHub v2
#
# Pulls latest code, installs deps, runs migrations, and restarts services
# one at a time with health-check validation. Rolls back on failure.
#
# Environment variables:
#   PROJECT_DIR     Path to the project root (default: /home/ubuntu/AALTOHUBv2)
#   GIT_BRANCH      Branch to deploy (default: main)
#   HEALTH_URL      Health check URL (default: http://localhost:8000/health)
#   HEALTH_RETRIES  Number of health check retries after restart (default: 12)
#   HEALTH_DELAY    Seconds between health check retries (default: 5)

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/AALTOHUBv2}"
GIT_BRANCH="${GIT_BRANCH:-main}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8000/health}"
HEALTH_RETRIES="${HEALTH_RETRIES:-12}"
HEALTH_DELAY="${HEALTH_DELAY:-5}"
VENV_DIR="${PROJECT_DIR}/backend/venv"
TIMESTAMP="$(date -u '+%Y%m%dT%H%M%SZ')"

log() {
    echo "[$(date -u '+%Y-%m-%d %H:%M:%S')] $1"
}

die() {
    log "FATAL: $1"
    exit 1
}

# ------------------------------------------------------------------
# Pre-flight checks
# ------------------------------------------------------------------
[ -d "${PROJECT_DIR}" ] || die "Project directory not found: ${PROJECT_DIR}"
[ -d "${PROJECT_DIR}/.git" ] || die "Not a git repository: ${PROJECT_DIR}"

log "========================================"
log "AaltoHub v2 Zero-Downtime Deployment"
log "Branch: ${GIT_BRANCH}"
log "Project: ${PROJECT_DIR}"
log "========================================"

# ------------------------------------------------------------------
# 1. Save rollback point
# ------------------------------------------------------------------
cd "${PROJECT_DIR}"
ROLLBACK_COMMIT=$(git rev-parse HEAD)
log "Rollback commit: ${ROLLBACK_COMMIT}"

# ------------------------------------------------------------------
# 2. Pull latest code
# ------------------------------------------------------------------
log "Step 1: Pulling latest code..."
git fetch origin "${GIT_BRANCH}" || die "git fetch failed"
git checkout "${GIT_BRANCH}" || die "git checkout failed"
git pull origin "${GIT_BRANCH}" || die "git pull failed"
NEW_COMMIT=$(git rev-parse HEAD)
log "Deployed commit: ${NEW_COMMIT}"

if [ "${ROLLBACK_COMMIT}" = "${NEW_COMMIT}" ]; then
    log "No new commits. Skipping deployment."
    exit 0
fi

# ------------------------------------------------------------------
# 3. Install / update Python dependencies
# ------------------------------------------------------------------
log "Step 2: Installing Python dependencies..."
if [ ! -d "${VENV_DIR}" ]; then
    python3 -m venv "${VENV_DIR}"
fi
source "${VENV_DIR}/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "${PROJECT_DIR}/backend/requirements.txt"

# ------------------------------------------------------------------
# 4. Run DB migrations (if migration scripts exist)
# ------------------------------------------------------------------
MIGRATION_DIR="${PROJECT_DIR}/supabase/migrations"
if [ -d "${MIGRATION_DIR}" ] && [ "$(ls -A "${MIGRATION_DIR}" 2>/dev/null)" ]; then
    log "Step 3: Running database migrations..."
    if command -v supabase &> /dev/null; then
        (cd "${PROJECT_DIR}" && supabase db push) || log "WARN: Migration push had issues -- check manually"
    else
        log "WARN: supabase CLI not found -- skipping migrations"
    fi
else
    log "Step 3: No migrations found -- skipping"
fi

# ------------------------------------------------------------------
# 5. Health check helper
# ------------------------------------------------------------------
wait_for_healthy() {
    local attempt=0
    while [ "${attempt}" -lt "${HEALTH_RETRIES}" ]; do
        attempt=$((attempt + 1))
        local status_code
        status_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${HEALTH_URL}" 2>/dev/null || echo "000")
        if [ "${status_code}" = "200" ]; then
            log "Health check passed (attempt ${attempt}/${HEALTH_RETRIES})"
            return 0
        fi
        log "Health check attempt ${attempt}/${HEALTH_RETRIES}: HTTP ${status_code} -- retrying in ${HEALTH_DELAY}s..."
        sleep "${HEALTH_DELAY}"
    done
    return 1
}

# ------------------------------------------------------------------
# 6. Restart API service (first)
# ------------------------------------------------------------------
log "Step 4: Restarting API service..."
if systemctl is-active --quiet aaltohub-api.service 2>/dev/null; then
    sudo systemctl restart aaltohub-api.service
    log "Waiting for API to become healthy..."
    if ! wait_for_healthy; then
        log "ROLLBACK: API failed health check after restart"
        log "Rolling back to ${ROLLBACK_COMMIT}..."
        git checkout "${ROLLBACK_COMMIT}"
        pip install --quiet -r "${PROJECT_DIR}/backend/requirements.txt"
        sudo systemctl restart aaltohub-api.service
        sleep 5
        if wait_for_healthy; then
            log "Rollback successful -- API is healthy on previous commit"
        else
            log "CRITICAL: Rollback also failed -- manual intervention required"
        fi
        exit 1
    fi
else
    log "WARN: aaltohub-api.service not active -- skipping API restart"
fi

# ------------------------------------------------------------------
# 7. Restart crawler service (after API is confirmed healthy)
# ------------------------------------------------------------------
log "Step 5: Restarting crawler service..."
if systemctl is-active --quiet aaltohub-crawler.service 2>/dev/null; then
    sudo systemctl restart aaltohub-crawler.service
    sleep 5
    if systemctl is-active --quiet aaltohub-crawler.service; then
        log "Crawler service restarted successfully"
    else
        log "WARN: Crawler service may not have started cleanly -- check logs"
    fi
else
    log "WARN: aaltohub-crawler.service not active -- skipping crawler restart"
fi

# ------------------------------------------------------------------
# 8. Final verification
# ------------------------------------------------------------------
log "Step 6: Final health verification..."
if wait_for_healthy; then
    log "========================================"
    log "Deployment complete!"
    log "Commit: ${NEW_COMMIT}"
    log "========================================"
    exit 0
else
    log "WARN: Final health check failed -- services may need attention"
    exit 1
fi
