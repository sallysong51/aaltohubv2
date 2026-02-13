#!/bin/bash
# AaltoHub v2 Log Directory Setup
#
# Purpose: Create log directories and set appropriate permissions
# Run this script as the deployment user (ubuntu) or root
#
# Usage:
#   chmod +x backend/scripts/setup_logs.sh
#   ./backend/scripts/setup_logs.sh

set -euo pipefail  # Exit on error, undefined variable, or pipe failure

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_ROOT="/home/ubuntu/AALTOHUBv2"
LOG_DIR="${PROJECT_ROOT}/logs"
LOG_USER="ubuntu"
LOG_GROUP="ubuntu"

echo -e "${GREEN}=== AaltoHub v2 Log Directory Setup ===${NC}"
echo ""

# Detect current user
CURRENT_USER=$(whoami)
echo "Current user: ${CURRENT_USER}"

# 1. Create log directory
echo -e "${YELLOW}[1/5] Creating log directory...${NC}"
if [ -d "$LOG_DIR" ]; then
    echo "✓ Log directory already exists: ${LOG_DIR}"
else
    mkdir -p "$LOG_DIR"
    echo "✓ Created log directory: ${LOG_DIR}"
fi

# 2. Set ownership
echo -e "${YELLOW}[2/5] Setting ownership...${NC}"
if [ "$CURRENT_USER" = "root" ]; then
    chown -R ${LOG_USER}:${LOG_GROUP} "$LOG_DIR"
    echo "✓ Set ownership to ${LOG_USER}:${LOG_GROUP}"
elif [ "$CURRENT_USER" = "$LOG_USER" ]; then
    echo "✓ Already running as ${LOG_USER}, ownership correct"
else
    echo -e "${RED}⚠ Warning: Running as ${CURRENT_USER}, not ${LOG_USER} or root${NC}"
    echo "  You may need to run: sudo chown -R ${LOG_USER}:${LOG_GROUP} ${LOG_DIR}"
fi

# 3. Set permissions (rwxr-xr-x for directory, rw-r--r-- for files)
echo -e "${YELLOW}[3/5] Setting permissions...${NC}"
chmod 755 "$LOG_DIR"
if [ -n "$(ls -A $LOG_DIR 2>/dev/null)" ]; then
    find "$LOG_DIR" -type f -exec chmod 644 {} \;
    echo "✓ Set permissions: directory=755, files=644"
else
    echo "✓ Set permissions: directory=755 (no files yet)"
fi

# 4. Test log rotation
echo -e "${YELLOW}[4/5] Testing log rotation...${NC}"
TEST_LOG="${LOG_DIR}/test-rotation.log"

# Create test log
echo "Test message $(date)" > "$TEST_LOG"
for i in {1..5}; do
    echo "Line ${i} - $(date)" >> "$TEST_LOG"
done

# Test Python RotatingFileHandler
python3 - <<'EOF'
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

log_file = Path("/home/ubuntu/AALTOHUBv2/logs/test-rotation.log")

# Create a small rotating handler for testing
handler = RotatingFileHandler(
    log_file,
    maxBytes=500,  # Very small for testing
    backupCount=3,
    encoding="utf-8",
)

logger = logging.getLogger("test")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# Write enough to trigger rotation
for i in range(20):
    logger.info(f"Test rotation message {i} - this should trigger file rotation")

print("✓ Rotation test completed")
EOF

# Show rotation results
if ls "${LOG_DIR}"/test-rotation.log.* >/dev/null 2>&1; then
    echo "✓ Rotation successful, backup files created:"
    ls -lh "${LOG_DIR}"/test-rotation.log*
    # Clean up test files
    rm -f "${LOG_DIR}"/test-rotation.log*
else
    echo -e "${YELLOW}⚠ No rotation occurred (file may not be large enough)${NC}"
    rm -f "$TEST_LOG"
fi

# 5. Verify systemd service can write
echo -e "${YELLOW}[5/5] Checking systemd service configuration...${NC}"

# Check if services are configured with ReadWritePaths
SERVICE_FILES=(
    "/etc/systemd/system/aaltohub-api.service"
    "/etc/systemd/system/aaltohub-live-crawler.service"
)

for service in "${SERVICE_FILES[@]}"; do
    if [ -f "$service" ]; then
        if grep -q "ReadWritePaths=${PROJECT_ROOT}" "$service"; then
            echo "✓ $(basename $service) has ReadWritePaths configured"
        else
            echo -e "${RED}✗ $(basename $service) missing ReadWritePaths${NC}"
            echo "  Add this line to [Service] section:"
            echo "  ReadWritePaths=${PROJECT_ROOT}"
        fi
    else
        echo -e "${YELLOW}⚠ $(basename $service) not installed yet${NC}"
    fi
done

echo ""
echo -e "${GREEN}=== Setup Complete ===${NC}"
echo ""
echo "Log directory: ${LOG_DIR}"
echo "Log files:"
echo "  - api.log (main backend)"
echo "  - crawler.log (crawler process)"
echo ""
echo "Next steps:"
echo "  1. Restart services to start logging:"
echo "     sudo systemctl restart aaltohub-api aaltohub-live-crawler"
echo ""
echo "  2. Verify logs are being written:"
echo "     tail -f ${LOG_DIR}/api.log"
echo "     tail -f ${LOG_DIR}/crawler.log"
echo ""
echo "  3. Check systemd journal alongside file logs:"
echo "     journalctl -u aaltohub-api -f"
echo ""
echo "  4. Monitor disk usage:"
echo "     du -sh ${LOG_DIR}/"
echo "     journalctl --disk-usage"
echo ""
