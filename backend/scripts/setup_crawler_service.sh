#!/bin/bash
# Setup AaltoHub Crawler as systemd service on AWS EC2

set -e

echo "================================================"
echo "AaltoHub v2 - Crawler Service Setup"
echo "================================================"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "❌ Please run as root (use sudo)"
  exit 1
fi

# Variables
SERVICE_NAME="aaltohub-crawler"
SERVICE_FILE="aaltohub-crawler.service"
SYSTEMD_DIR="/etc/systemd/system"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "📁 Project root: $PROJECT_ROOT"
echo "📄 Service file: $SCRIPT_DIR/$SERVICE_FILE"

# Copy service file
echo "📋 Copying service file to systemd..."
cp "$SCRIPT_DIR/$SERVICE_FILE" "$SYSTEMD_DIR/$SERVICE_FILE"

# Reload systemd
echo "🔄 Reloading systemd daemon..."
systemctl daemon-reload

# Enable service (auto-start on boot)
echo "✅ Enabling $SERVICE_NAME service..."
systemctl enable $SERVICE_NAME

# Create log files with correct permissions
echo "📝 Creating log files..."
touch /var/log/aaltohub-crawler.log
touch /var/log/aaltohub-crawler-error.log
chown ubuntu:ubuntu /var/log/aaltohub-crawler.log
chown ubuntu:ubuntu /var/log/aaltohub-crawler-error.log

echo ""
echo "================================================"
echo "✅ Service setup complete!"
echo "================================================"
echo ""
echo "Available commands:"
echo "  Start crawler:   sudo systemctl start $SERVICE_NAME"
echo "  Stop crawler:    sudo systemctl stop $SERVICE_NAME"
echo "  Restart crawler: sudo systemctl restart $SERVICE_NAME"
echo "  View status:     sudo systemctl status $SERVICE_NAME"
echo "  View logs:       sudo journalctl -u $SERVICE_NAME -f"
echo "  View log file:   tail -f /var/log/aaltohub-crawler.log"
echo ""
echo "Auto-start on boot: ENABLED"
echo ""
