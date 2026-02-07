#!/bin/bash
# Setup systemd service for AaltoHub crawler on EC2

set -e

echo "======================================"
echo "AaltoHub v2 Crawler Service Setup"
echo "======================================"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

# Create log directory
echo "Creating log directory..."
mkdir -p /var/log/aaltohub
chown ubuntu:ubuntu /var/log/aaltohub

# Copy systemd service file
echo "Copying systemd service file..."
cp /home/ubuntu/AALTOHUBv2/systemd/aaltohub-crawler.service /etc/systemd/system/

# Reload systemd daemon
echo "Reloading systemd daemon..."
systemctl daemon-reload

# Enable service to start on boot
echo "Enabling service to start on boot..."
systemctl enable aaltohub-crawler.service

# Start the service
echo "Starting crawler service..."
systemctl start aaltohub-crawler.service

# Check status
echo ""
echo "Service status:"
systemctl status aaltohub-crawler.service --no-pager

echo ""
echo "======================================"
echo "Setup complete!"
echo "======================================"
echo ""
echo "Useful commands:"
echo "  - Check status:  sudo systemctl status aaltohub-crawler"
echo "  - View logs:     sudo journalctl -u aaltohub-crawler -f"
echo "  - Stop service:  sudo systemctl stop aaltohub-crawler"
echo "  - Start service: sudo systemctl start aaltohub-crawler"
echo "  - Restart:       sudo systemctl restart aaltohub-crawler"
echo ""
