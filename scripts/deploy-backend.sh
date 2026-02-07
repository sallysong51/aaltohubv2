#!/bin/bash
# Deploy backend to EC2 server

set -e

echo "======================================"
echo "AaltoHub v2 Backend Deployment"
echo "======================================"

# Configuration
EC2_HOST="ubuntu@your-ec2-ip"
PROJECT_DIR="/home/ubuntu/AALTOHUBv2"

echo "Deploying to: $EC2_HOST"
echo ""

# 1. Sync backend code
echo "1. Syncing backend code..."
rsync -avz --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
    backend/ $EC2_HOST:$PROJECT_DIR/backend/

# 2. Sync systemd service files
echo "2. Syncing systemd service files..."
rsync -avz systemd/ $EC2_HOST:$PROJECT_DIR/systemd/

# 3. Sync scripts
echo "3. Syncing deployment scripts..."
rsync -avz scripts/ $EC2_HOST:$PROJECT_DIR/scripts/

# 4. SSH into server and restart services
echo "4. Restarting services on server..."
ssh $EC2_HOST << 'ENDSSH'
cd /home/ubuntu/AALTOHUBv2/backend

# Activate virtual environment
source venv/bin/activate

# Install/update dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Restart FastAPI service (if using systemd)
if systemctl is-active --quiet aaltohub-api.service; then
    echo "Restarting API service..."
    sudo systemctl restart aaltohub-api.service
else
    echo "API service not running. Start manually or setup systemd service."
fi

# Restart crawler service
if systemctl is-active --quiet aaltohub-crawler.service; then
    echo "Restarting crawler service..."
    sudo systemctl restart aaltohub-crawler.service
else
    echo "Crawler service not running. Start with: sudo systemctl start aaltohub-crawler"
fi

# Check service status
echo ""
echo "Service statuses:"
systemctl status aaltohub-api.service --no-pager || echo "API service not configured"
systemctl status aaltohub-crawler.service --no-pager || echo "Crawler service not configured"

ENDSSH

echo ""
echo "======================================"
echo "Deployment complete!"
echo "======================================"
