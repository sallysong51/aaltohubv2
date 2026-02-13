"""
Systemd watchdog integration for crawler process health monitoring.

The watchdog sends periodic heartbeats to systemd (via sd_notify) to prove
the crawler is still responsive. If heartbeats stop (process hangs, deadlock,
infinite loop), systemd automatically restarts the service.

Architecture:
  - Runs in background asyncio task (started from crawler_main.py lifespan)
  - Checks crawler health every 30s (configurable)
  - Sends "WATCHDOG=1" to systemd if healthy
  - Skips heartbeat if unhealthy → systemd restarts after WatchdogSec timeout
  - Sends "READY=1" on startup to signal initialization complete

Health criteria:
  - All Telegram clients connected (clients.is_connected())
  - Message queue not critically full (<90% of maxsize)
  - Crawler in 'running' state

Requirements:
  - systemd service with Type=notify and WatchdogSec=120 (see systemd/*.service)
  - pip install sdnotify
"""
import asyncio
import logging
from typing import TYPE_CHECKING

try:
    import sdnotify
    SDNOTIFY_AVAILABLE = True
except ImportError:
    SDNOTIFY_AVAILABLE = False

if TYPE_CHECKING:
    from app.live_crawler import LiveCrawlerService

logger = logging.getLogger(__name__)

# Watchdog interval must be less than systemd WatchdogSec (120s)
# We check every 30s to give 4x safety margin
WATCHDOG_INTERVAL_SEC = 30

# Message queue health threshold (90% full = unhealthy)
QUEUE_HEALTH_THRESHOLD = 0.9


class CrawlerWatchdog:
    """Systemd watchdog for crawler process health monitoring.

    Sends periodic sd_notify heartbeats to systemd to prove the crawler
    is still responsive. If the process hangs or becomes unhealthy,
    systemd will restart it after WatchdogSec timeout.

    Usage:
        watchdog = CrawlerWatchdog(live_crawler)
        await watchdog.start()  # Runs until cancelled
    """

    def __init__(self, crawler: "LiveCrawlerService"):
        """Initialize watchdog.

        Args:
            crawler: LiveCrawlerService instance to monitor
        """
        self._crawler = crawler
        self._notifier = sdnotify.SystemdNotifier() if SDNOTIFY_AVAILABLE else None
        self._running = False

        if not SDNOTIFY_AVAILABLE:
            logger.warning(
                "[WATCHDOG] sdnotify not available — systemd watchdog disabled. "
                "Install with: pip install sdnotify"
            )
        elif not self._notifier.enabled():
            logger.info(
                "[WATCHDOG] systemd watchdog not enabled (not running under systemd "
                "or WatchdogSec not set). Heartbeat loop will run but have no effect."
            )
        else:
            logger.info("[WATCHDOG] Systemd watchdog enabled")

    def notify_ready(self) -> None:
        """Notify systemd that the service has finished initialization.

        This should be called once after the crawler has successfully started.
        Systemd will wait for this signal before considering the service active.
        """
        if self._notifier and self._notifier.enabled():
            self._notifier.notify("READY=1")
            logger.info("[WATCHDOG] Sent READY=1 to systemd")

    def _is_healthy(self) -> bool:
        """Check if crawler is in healthy state.

        Health criteria:
          - Crawler is running
          - All Telegram clients are connected
          - Message queue is not critically full (<90% capacity)

        Returns:
            True if healthy, False otherwise
        """
        # Import here to avoid circular dependency
        from app.live_crawler import MSG_QUEUE_MAXSIZE

        if not self._crawler.running:
            logger.debug("[WATCHDOG] Unhealthy: crawler not running")
            return False

        # Check if all clients are connected
        if not self._crawler.clients:
            logger.debug("[WATCHDOG] Unhealthy: no clients connected")
            return False

        disconnected_clients = [
            user_id
            for user_id, client in self._crawler.clients.items()
            if not client.is_connected()
        ]
        if disconnected_clients:
            logger.warning(
                "[WATCHDOG] Unhealthy: %d client(s) disconnected: %s",
                len(disconnected_clients),
                disconnected_clients
            )
            return False

        # Check message queue health
        queue_size = self._crawler._msg_queue.qsize()
        queue_threshold = int(MSG_QUEUE_MAXSIZE * QUEUE_HEALTH_THRESHOLD)
        if queue_size >= queue_threshold:
            logger.warning(
                "[WATCHDOG] Unhealthy: message queue critically full "
                "(%d/%d, threshold=%d)",
                queue_size, MSG_QUEUE_MAXSIZE, queue_threshold
            )
            return False

        return True

    async def start(self) -> None:
        """Start the watchdog heartbeat loop.

        This runs indefinitely until cancelled. Checks crawler health every
        WATCHDOG_INTERVAL_SEC seconds and sends heartbeat to systemd if healthy.

        If unhealthy, skips the heartbeat — systemd will restart the service
        after WatchdogSec timeout (default 120s).

        Raises:
            asyncio.CancelledError: When task is cancelled (normal shutdown)
        """
        if not SDNOTIFY_AVAILABLE:
            logger.info("[WATCHDOG] Heartbeat loop disabled (sdnotify not available)")
            # Keep task alive but do nothing
            try:
                await asyncio.Event().wait()  # Sleep forever
            except asyncio.CancelledError:
                logger.info("[WATCHDOG] Heartbeat loop cancelled")
                raise
            return

        self._running = True
        logger.info(
            "[WATCHDOG] Starting heartbeat loop (interval=%ds, systemd enabled=%s)",
            WATCHDOG_INTERVAL_SEC,
            self._notifier.enabled() if self._notifier else False
        )

        try:
            while True:
                await asyncio.sleep(WATCHDOG_INTERVAL_SEC)

                if self._is_healthy():
                    # Send heartbeat to systemd
                    if self._notifier and self._notifier.enabled():
                        self._notifier.notify("WATCHDOG=1")
                        logger.debug("[WATCHDOG] Sent heartbeat to systemd (healthy)")
                    else:
                        logger.debug("[WATCHDOG] Healthy (systemd not enabled, no heartbeat sent)")
                else:
                    # Unhealthy — skip heartbeat, let systemd restart
                    logger.error(
                        "[WATCHDOG] Unhealthy, skipping heartbeat. "
                        "Systemd will restart after WatchdogSec timeout."
                    )
                    # Don't break the loop — maybe crawler will recover before timeout

        except asyncio.CancelledError:
            logger.info("[WATCHDOG] Heartbeat loop cancelled (shutdown)")
            self._running = False
            raise

        except Exception as e:
            logger.exception("[WATCHDOG] Heartbeat loop crashed: %s", e)
            self._running = False
            raise
