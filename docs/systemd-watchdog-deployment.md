# Systemd Watchdog Deployment Guide (Phase 34)

## Overview

Systemd watchdog integration provides automatic recovery from process hangs, deadlocks, and unresponsive states. The crawler sends periodic heartbeats to systemd; if heartbeats stop, systemd automatically restarts the service.

## Architecture

### Components

1. **app/watchdog.py** - CrawlerWatchdog class
   - Sends `WATCHDOG=1` to systemd every 30s if healthy
   - Checks health: all clients connected + queue <90% full
   - Sends `READY=1` after initialization

2. **crawler_main.py** - Integration layer
   - Creates watchdog instance in lifespan
   - Starts watchdog background task
   - Calls `notify_ready()` after crawler starts

3. **systemd service** - Process supervisor
   - `Type=notify` - waits for READY=1 signal
   - `WatchdogSec=120` - restarts if no heartbeat for 120s
   - Restart limits: 5 failures in 10 minutes → stop

### Health Criteria

Watchdog marks the crawler as healthy when ALL of:
- Crawler is in `running` state
- At least one Telegram client exists
- All Telegram clients are connected (`client.is_connected()`)
- Message queue is <90% full (`qsize < 9000/10000`)

If any criterion fails, heartbeat is skipped → systemd restarts after 120s.

## Deployment Steps

### 1. Install Dependencies

```bash
cd /home/ubuntu/AALTOHUBv2/backend
source venv/bin/activate
pip install sdnotify>=0.3.2
```

### 2. Update Systemd Service

```bash
# Copy updated service file
sudo cp /home/ubuntu/AALTOHUBv2/systemd/aaltohub-live-crawler.service /etc/systemd/system/

# Reload systemd configuration
sudo systemctl daemon-reload

# Verify service configuration
systemctl cat aaltohub-live-crawler.service | grep -A2 "Type=notify"
# Should show:
#   Type=notify
#   ...
#   WatchdogSec=120
```

### 3. Restart Service

```bash
# Restart crawler with new watchdog
sudo systemctl restart aaltohub-live-crawler

# Check status (should show "active (running)")
sudo systemctl status aaltohub-live-crawler

# Verify watchdog is enabled
journalctl -u aaltohub-live-crawler -n 50 | grep WATCHDOG
# Should show:
#   [WATCHDOG] Systemd watchdog enabled
#   [WATCHDOG] Systemd watchdog initialized
#   [WATCHDOG] Sent READY=1 to systemd
#   [WATCHDOG] Sent heartbeat to systemd (healthy)
```

### 4. Verify Watchdog Operation

```bash
# Monitor watchdog heartbeats (real-time)
journalctl -u aaltohub-live-crawler -f | grep WATCHDOG

# Expected output every 30s:
#   [WATCHDOG] Sent heartbeat to systemd (healthy)

# If unhealthy, you'll see:
#   [WATCHDOG] Unhealthy: X client(s) disconnected: [123, 456]
#   [WATCHDOG] Unhealthy, skipping heartbeat. Systemd will restart after WatchdogSec timeout.
```

## Monitoring & Diagnostics

### Check Watchdog Status

```bash
# View recent watchdog logs
journalctl -u aaltohub-live-crawler -n 100 | grep -E "WATCHDOG|Restart"

# Count restarts triggered by watchdog timeout
journalctl -u aaltohub-live-crawler --since "1 day ago" | grep "Watchdog timeout"

# View crawler health metrics
curl -H "Authorization: Bearer $CRAWLER_API_SECRET" http://127.0.0.1:8001/health
```

### Expected Log Patterns

**Healthy operation:**
```
[WATCHDOG] Starting heartbeat loop (interval=30s, systemd enabled=True)
[WATCHDOG] Sent heartbeat to systemd (healthy)  # Every 30s
```

**Unhealthy - disconnected clients:**
```
[WATCHDOG] Unhealthy: 2 client(s) disconnected: [123456789, 987654321]
[WATCHDOG] Unhealthy, skipping heartbeat. Systemd will restart after WatchdogSec timeout.
```

**Unhealthy - queue overload:**
```
[WATCHDOG] Unhealthy: message queue critically full (9100/10000, threshold=9000)
[WATCHDOG] Unhealthy, skipping heartbeat. Systemd will restart after WatchdogSec timeout.
```

**Systemd restart:**
```
systemd[1]: aaltohub-live-crawler.service: Watchdog timeout (limit 2min)!
systemd[1]: aaltohub-live-crawler.service: Killing process ...
systemd[1]: aaltohub-live-crawler.service: Main process exited, code=killed, status=6/ABRT
systemd[1]: aaltohub-live-crawler.service: Failed with result 'watchdog'.
systemd[1]: aaltohub-live-crawler.service: Scheduled restart job, restart counter is at 1.
```

## Troubleshooting

### Watchdog Not Enabled

**Symptom:** Logs show "systemd watchdog not enabled"

**Causes:**
1. Not running under systemd (e.g., manual `uvicorn` run)
2. `Type=notify` not set in service file
3. `WatchdogSec` not set or commented out

**Fix:**
```bash
# Verify service file has Type=notify and WatchdogSec=120
systemctl cat aaltohub-live-crawler.service | grep -E "Type=|WatchdogSec="

# If missing, update service file and reload
sudo cp systemd/aaltohub-live-crawler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart aaltohub-live-crawler
```

### Frequent Restarts

**Symptom:** Service restarts every 120s

**Causes:**
1. Clients frequently disconnecting (network issues, FloodWait)
2. Message queue consistently full (DB slow, high message volume)
3. Crawler entering unhealthy state intermittently

**Diagnosis:**
```bash
# Check what's causing unhealthy state
journalctl -u aaltohub-live-crawler -n 200 | grep "Unhealthy"

# Common patterns:
#   "client(s) disconnected" → network/FloodWait issue
#   "queue critically full" → DB bottleneck or message spike
```

**Fixes:**
- Disconnected clients: Check network, increase FloodWait tolerance
- Queue full: Tune `BATCH_SIZE`, check DB performance, add indices
- Temporary spikes: Increase `WatchdogSec` to 180s or 240s for more tolerance

### sdnotify Import Error

**Symptom:** `ImportError: No module named 'sdnotify'`

**Fix:**
```bash
cd /home/ubuntu/AALTOHUBv2/backend
source venv/bin/activate
pip install sdnotify>=0.3.2
sudo systemctl restart aaltohub-live-crawler
```

### Watchdog Task Not Starting

**Symptom:** No watchdog logs after startup

**Diagnosis:**
```bash
# Check for Python exceptions
journalctl -u aaltohub-live-crawler -n 100 | grep -E "Exception|Error|Traceback"

# Verify watchdog task creation
journalctl -u aaltohub-live-crawler -n 100 | grep "systemd-watchdog"
```

**Common issues:**
- Circular import → check `app/watchdog.py` imports
- Task creation failure → check `_safe_create_task()` error logs

## Configuration Tuning

### Adjust Watchdog Interval

If 30s is too aggressive (frequent false positives):

**app/watchdog.py:**
```python
# Change from 30s to 45s
WATCHDOG_INTERVAL_SEC = 45
```

**systemd service:**
```ini
# Increase timeout proportionally (45s * 4 = 180s safety margin)
WatchdogSec=180
```

### Adjust Queue Health Threshold

If 90% is too strict:

**app/watchdog.py:**
```python
# Change from 90% to 95%
QUEUE_HEALTH_THRESHOLD = 0.95
```

### Disable Watchdog (Development)

To disable watchdog without code changes:

**systemd service:**
```ini
# Comment out WatchdogSec
# WatchdogSec=120
```

Watchdog will still run but have no effect (systemd won't enforce timeout).

## Metrics & Alerting

### Prometheus Metrics (Future)

Add watchdog metrics to `/metrics` endpoint:

- `watchdog_heartbeat_total` (counter) - Total heartbeats sent
- `watchdog_unhealthy_total` (counter) - Times marked unhealthy
- `watchdog_healthy` (gauge) - Current health status (0/1)

### Sentry Alerts

Watchdog already logs to Sentry on critical errors. To add custom alerts:

**app/watchdog.py** (_is_healthy method):
```python
if not healthy:
    sentry_sdk.capture_message(
        f"Watchdog marked unhealthy: {reason}",
        level="warning",
        extras={"disconnected_clients": ..., "queue_size": ...}
    )
```

## Rollback Plan

If watchdog causes stability issues:

1. **Immediate:** Comment out WatchdogSec in service file
   ```bash
   sudo nano /etc/systemd/system/aaltohub-live-crawler.service
   # Add # before WatchdogSec=120
   sudo systemctl daemon-reload
   sudo systemctl restart aaltohub-live-crawler
   ```

2. **If needed:** Revert to Type=simple
   ```bash
   # Change Type=notify → Type=simple
   sudo systemctl daemon-reload
   sudo systemctl restart aaltohub-live-crawler
   ```

3. **Full rollback:** Restore previous service file from git
   ```bash
   cd /home/ubuntu/AALTOHUBv2
   git checkout HEAD~1 systemd/aaltohub-live-crawler.service
   sudo cp systemd/aaltohub-live-crawler.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl restart aaltohub-live-crawler
   ```

## Testing Strategy

### 1. Normal Operation Test

```bash
# Start service and monitor for 5 minutes
sudo systemctl restart aaltohub-live-crawler
journalctl -u aaltohub-live-crawler -f | grep WATCHDOG

# Expected: Heartbeat every 30s, no restarts
```

### 2. Unhealthy Client Simulation

```python
# In crawler Python shell or admin API
from app.live_crawler import live_crawler

# Manually disconnect all clients (triggers unhealthy state)
for client in live_crawler.clients.values():
    await client.disconnect()

# Watch logs: should show "Unhealthy: X client(s) disconnected"
# After 120s: systemd should restart the service
```

### 3. Queue Overflow Simulation

```python
# Fill queue to 95% (triggers unhealthy state)
from app.live_crawler import live_crawler, MSG_QUEUE_MAXSIZE

for i in range(int(MSG_QUEUE_MAXSIZE * 0.95)):
    try:
        live_crawler._msg_queue.put_nowait({"test": i})
    except asyncio.QueueFull:
        break

# Watch logs: should show "message queue critically full"
# After 120s: systemd should restart the service
```

### 4. Graceful Restart Test

```bash
# Restart should complete within TimeoutStopSec (60s)
sudo systemctl restart aaltohub-live-crawler

# Verify no SIGKILL in logs
journalctl -u aaltohub-live-crawler -n 50 | grep -E "SIGKILL|killed"
# Should be empty (graceful shutdown with SIGTERM only)
```

## Performance Impact

- **CPU overhead:** <0.1% (30s sleep loop)
- **Memory overhead:** <1MB (watchdog task + sdnotify)
- **Network overhead:** None (local systemd socket)
- **Latency impact:** None (heartbeat is async)

## Conclusion

Systemd watchdog provides automatic recovery from:
- Process hangs (infinite loops, deadlocks)
- Unresponsive clients (all clients stuck in FloodWait)
- Queue overload (DB bottleneck, message storm)

Trade-off: 120s delay before restart (can tune WatchdogSec if needed).

For questions or issues, see Troubleshooting section or check logs:
```bash
journalctl -u aaltohub-live-crawler -n 500 | grep -E "WATCHDOG|Error|Exception"
```
