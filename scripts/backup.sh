#!/usr/bin/env bash
# backup.sh -- Database backup script for AaltoHub v2
#
# Uses pg_dump to create timestamped database backups.
# Retains the last 7 daily backups and removes older ones.
#
# Environment variables (required):
#   DATABASE_URL       PostgreSQL connection string (e.g. postgresql://user:pass@host:5432/dbname)
#                      or individual PG* variables below
#   PGHOST             Database host (used if DATABASE_URL is not set)
#   PGPORT             Database port (default: 5432)
#   PGUSER             Database user
#   PGPASSWORD         Database password
#   PGDATABASE         Database name
#
# Environment variables (optional):
#   BACKUP_DIR         Directory to store backups (default: /var/backups/aaltohub)
#   BACKUP_RETAIN      Number of daily backups to retain (default: 7)

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/aaltohub}"
BACKUP_RETAIN="${BACKUP_RETAIN:-7}"
TIMESTAMP="$(date -u '+%Y%m%d_%H%M%S')"
BACKUP_FILE="${BACKUP_DIR}/aaltohub_${TIMESTAMP}.sql.gz"

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
command -v pg_dump &> /dev/null || die "pg_dump not found -- install postgresql-client"
command -v gzip &> /dev/null || die "gzip not found"

if [ -z "${DATABASE_URL:-}" ] && [ -z "${PGHOST:-}" ]; then
    die "Either DATABASE_URL or PGHOST must be set"
fi

# Create backup directory if it doesn't exist
mkdir -p "${BACKUP_DIR}" || die "Cannot create backup directory: ${BACKUP_DIR}"

log "========================================"
log "AaltoHub v2 Database Backup"
log "Backup dir: ${BACKUP_DIR}"
log "Retention:  ${BACKUP_RETAIN} backups"
log "========================================"

# ------------------------------------------------------------------
# 1. Run pg_dump
# ------------------------------------------------------------------
log "Step 1: Creating database backup..."

if [ -n "${DATABASE_URL:-}" ]; then
    pg_dump "${DATABASE_URL}" \
        --no-owner \
        --no-acl \
        --clean \
        --if-exists \
        2>/dev/null | gzip > "${BACKUP_FILE}"
else
    PGPORT="${PGPORT:-5432}"
    PGPASSWORD="${PGPASSWORD:-}" pg_dump \
        -h "${PGHOST}" \
        -p "${PGPORT}" \
        -U "${PGUSER}" \
        -d "${PGDATABASE}" \
        --no-owner \
        --no-acl \
        --clean \
        --if-exists \
        2>/dev/null | gzip > "${BACKUP_FILE}"
fi

# ------------------------------------------------------------------
# 2. Verify backup
# ------------------------------------------------------------------
log "Step 2: Verifying backup..."

if [ ! -f "${BACKUP_FILE}" ]; then
    die "Backup file was not created: ${BACKUP_FILE}"
fi

BACKUP_SIZE=$(stat -f%z "${BACKUP_FILE}" 2>/dev/null || stat -c%s "${BACKUP_FILE}" 2>/dev/null || echo "0")

if [ "${BACKUP_SIZE}" -eq 0 ]; then
    rm -f "${BACKUP_FILE}"
    die "Backup file is empty -- database dump likely failed"
fi

log "Backup created: ${BACKUP_FILE} (${BACKUP_SIZE} bytes)"

# ------------------------------------------------------------------
# 3. Rotate old backups (keep last N)
# ------------------------------------------------------------------
log "Step 3: Rotating old backups (keeping last ${BACKUP_RETAIN})..."

BACKUP_COUNT=$(ls -1 "${BACKUP_DIR}"/aaltohub_*.sql.gz 2>/dev/null | wc -l | tr -d ' ')
log "Current backup count: ${BACKUP_COUNT}"

if [ "${BACKUP_COUNT}" -gt "${BACKUP_RETAIN}" ]; then
    REMOVE_COUNT=$((BACKUP_COUNT - BACKUP_RETAIN))
    # Sort by name (which includes timestamp) and remove the oldest
    ls -1 "${BACKUP_DIR}"/aaltohub_*.sql.gz | sort | head -n "${REMOVE_COUNT}" | while read -r old_backup; do
        log "Removing old backup: $(basename "${old_backup}")"
        rm -f "${old_backup}"
    done
    log "Removed ${REMOVE_COUNT} old backup(s)"
else
    log "No backups to remove (${BACKUP_COUNT} <= ${BACKUP_RETAIN})"
fi

# ------------------------------------------------------------------
# 4. Summary
# ------------------------------------------------------------------
REMAINING=$(ls -1 "${BACKUP_DIR}"/aaltohub_*.sql.gz 2>/dev/null | wc -l | tr -d ' ')
log "========================================"
log "Backup complete!"
log "File: ${BACKUP_FILE}"
log "Size: ${BACKUP_SIZE} bytes"
log "Backups on disk: ${REMAINING}"
log "========================================"

exit 0
