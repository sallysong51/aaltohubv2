# AaltoHub v2 Systemd Configuration

This directory contains systemd service files and journald configuration for running AaltoHub v2 services.

## Service Files

### 1. aaltohub-api.service
Main FastAPI backend service running on port 8000.

**Installation:**
```bash
sudo cp systemd/aaltohub-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aaltohub-api
sudo systemctl start aaltohub-api
```

**Check status:**
```bash
sudo systemctl status aaltohub-api
journalctl -u aaltohub-api -f
```

### 2. aaltohub-live-crawler.service
Live crawler process running on port 8001 (localhost only).

**Installation:**
```bash
sudo cp systemd/aaltohub-live-crawler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aaltohub-live-crawler
sudo systemctl start aaltohub-live-crawler
```

**Check status:**
```bash
sudo systemctl status aaltohub-live-crawler
journalctl -u aaltohub-live-crawler -f
```

## journald Configuration

### journald-aaltohub.conf
Prevents systemd journal from filling disk space with logs.

**Installation:**
```bash
# Create journald drop-in directory if it doesn't exist
sudo mkdir -p /etc/systemd/journald.conf.d/

# Copy configuration file
sudo cp systemd/journald-aaltohub.conf /etc/systemd/journald.conf.d/

# Restart journald to apply changes
sudo systemctl restart systemd-journald
```

**Verification:**
```bash
# Check total disk usage by journal
journalctl --disk-usage

# View recent logs
journalctl -u aaltohub-api -n 100
journalctl -u aaltohub-live-crawler -n 100

# View logs since last boot
journalctl -u aaltohub-api -b

# Follow logs in real-time
journalctl -u aaltohub-api -f
```

**Configuration Summary:**
- **SystemMaxUse**: 1GB maximum disk space
- **MaxRetentionSec**: Keep logs for 7 days
- **Compress**: Yes (saves ~50% disk space)
- **SystemMaxFileSize**: 100MB per journal file
- **RateLimitIntervalSec**: 30s
- **RateLimitBurst**: 1000 lines per 30 seconds

## Log Files

In addition to systemd journal, services write to rotating log files:
- **Location**: `/home/ubuntu/AALTOHUBv2/logs/`
- **Files**: `api.log`, `crawler.log`
- **Rotation**: 50MB per file, 5 backups (250MB total per service)
- **Format**: JSON in production, human-readable in development

**View log files:**
```bash
# Latest logs
tail -f /home/ubuntu/AALTOHUBv2/logs/api.log
tail -f /home/ubuntu/AALTOHUBv2/logs/crawler.log

# Search in logs (JSON format in production)
cat /home/ubuntu/AALTOHUBv2/logs/api.log | grep "ERROR"
cat /home/ubuntu/AALTOHUBv2/logs/crawler.log | jq '.level' | sort | uniq -c
```

## Troubleshooting

### Service won't start
```bash
# Check for errors in service file
sudo systemd-analyze verify aaltohub-api.service

# View full status including logs
sudo systemctl status aaltohub-api -l

# Check journal for startup errors
journalctl -u aaltohub-api -n 50 --no-pager
```

### Disk space issues
```bash
# Manually clean old journal entries
sudo journalctl --vacuum-time=3d  # Keep last 3 days
sudo journalctl --vacuum-size=500M  # Keep last 500MB

# Check current journal usage
journalctl --disk-usage

# Verify journald config is applied
systemctl status systemd-journald
journalctl --header  # Shows runtime settings
```

### Log rotation not working
```bash
# Check log directory permissions
ls -la /home/ubuntu/AALTOHUBv2/logs/

# Manually trigger rotation (for testing)
python3 -c "
from logging.handlers import RotatingFileHandler
handler = RotatingFileHandler('/home/ubuntu/AALTOHUBv2/logs/api.log', maxBytes=1000, backupCount=5)
handler.doRollover()
"

# Check for .log.1, .log.2, etc files
ls -lh /home/ubuntu/AALTOHUBv2/logs/
```

## Restart Services

```bash
# Restart individual service
sudo systemctl restart aaltohub-api
sudo systemctl restart aaltohub-live-crawler

# Restart all AaltoHub services
sudo systemctl restart aaltohub-*

# Reload systemd configuration (after editing .service files)
sudo systemctl daemon-reload
```
