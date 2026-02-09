"""Error Recovery & Resilience — Caching, retries, circuit breaker for Telegram API calls.

Handles transient failures gracefully with:
- Result caching (5-min TTL)
- Retry logic (3 attempts with exponential backoff)
- Circuit breaker pattern (open after 5 consecutive failures)
- Sentry alerting on persistent failures
- Periodic cleanup to prevent unbounded memory growth
"""
import asyncio
import logging
import time
from telethon import TelegramClient

logger = logging.getLogger(__name__)


class GetMeErrorRecovery:
    """Resilient get_me() calls with caching, retries, and circuit breaker.

    Phase 2A: Error Recovery & Resilience.

    Usage:
        recovery = GetMeErrorRecovery()
        telegram_user_id = await recovery.get_telegram_user_id_with_retry(client, user_id)
    """

    def __init__(self):
        """Initialize error recovery tracking."""
        # Cache telegram_user_id per user_id (user_id -> (telegram_user_id, timestamp))
        self._get_me_cache: dict[int, tuple[int, float]] = {}
        self._get_me_cache_ttl = 300.0  # 5 minutes

        # Track get_me() failures per user_id for circuit breaker
        self._get_me_failure_count: dict[int, int] = {}
        self._get_me_circuit_open: dict[int, float] = {}  # user_id -> time when circuit opens
        self._get_me_circuit_backoff = 30.0  # 30s initial backoff

    async def get_telegram_user_id_with_retry(
        self, client: TelegramClient, user_id: int | None
    ) -> int | None:
        """Get telegram_user_id with caching, retries, and circuit breaker.

        Args:
            client: TelegramClient instance
            user_id: Optional admin user ID (for error tracking)

        Returns:
            telegram_user_id (int) or None if failed after retries
        """
        if user_id is None:
            # Unable to track errors without user_id, just try once
            try:
                me = await asyncio.wait_for(client.get_me(), timeout=5.0)
                return int(me.id) if me and me.id else None
            except Exception as e:
                logger.warning("get_me() failed (no user_id for tracking): %s", e)
                return None

        # Check cache first
        if user_id in self._get_me_cache:
            cached_user_id, timestamp = self._get_me_cache[user_id]
            if time.monotonic() - timestamp < self._get_me_cache_ttl:
                logger.debug("get_telegram_user_id_with_retry: cache hit for user %s", user_id)
                return cached_user_id

        # Check if circuit is open (backoff active)
        if user_id in self._get_me_circuit_open:
            circuit_open_at = self._get_me_circuit_open[user_id]
            if time.monotonic() - circuit_open_at < self._get_me_circuit_backoff:
                logger.debug(
                    "get_telegram_user_id_with_retry: circuit open for user %s, backoff active",
                    user_id,
                )
                return None

        # Retry logic: up to 3 attempts
        max_retries = 3
        for attempt in range(max_retries):
            try:
                me = await asyncio.wait_for(client.get_me(), timeout=5.0)
                if not me or not me.id:
                    logger.warning(
                        "get_telegram_user_id_with_retry: get_me() returned empty for user %s (attempt %d/%d)",
                        user_id,
                        attempt + 1,
                        max_retries,
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.5)
                    continue

                my_telegram_user_id = int(me.id)

                # Cache the result
                self._get_me_cache[user_id] = (my_telegram_user_id, time.monotonic())
                self._get_me_failure_count[user_id] = 0  # Reset failure counter

                logger.debug(
                    "get_telegram_user_id_with_retry: get_me() success for user %s -> telegram_user_id %s",
                    user_id,
                    my_telegram_user_id,
                )
                return my_telegram_user_id

            except asyncio.TimeoutError:
                logger.warning(
                    "get_telegram_user_id_with_retry: get_me() timeout for user %s (attempt %d/%d)",
                    user_id,
                    attempt + 1,
                    max_retries,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.0)
                continue

            except Exception as e:
                logger.warning(
                    "get_telegram_user_id_with_retry: get_me() error for user %s (attempt %d/%d): %s",
                    user_id,
                    attempt + 1,
                    max_retries,
                    e,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5)
                continue

        # All retries exhausted: circuit breaker
        self._get_me_failure_count[user_id] = self._get_me_failure_count.get(user_id, 0) + 1
        failure_count = self._get_me_failure_count[user_id]

        # Open circuit after 5 consecutive failures
        if failure_count >= 5:
            self._get_me_circuit_open[user_id] = time.monotonic()
            logger.error(
                "get_telegram_user_id_with_retry: circuit opened for user %s after %d consecutive failures",
                user_id,
                failure_count,
            )
            # Alert Sentry
            try:
                import sentry_sdk

                sentry_sdk.capture_exception(
                    Exception(
                        f"get_me() circuit breaker open for user {user_id} after {failure_count} failures"
                    )
                )
            except Exception:
                pass

        logger.error(
            "get_telegram_user_id_with_retry: failed to get telegram_user_id for user %s after %d retries",
            user_id,
            max_retries,
        )
        return None

    async def cleanup(self) -> None:
        """Periodic cleanup of caches to prevent unbounded growth.

        Removes:
        - Expired cache entries (older than 2x TTL)
        - Closed circuits (backoff period expired)
        - Stale failure counters
        """
        try:
            now = time.monotonic()
            stale_users = []

            # Clean expired cache entries
            for user_id, (_, timestamp) in list(self._get_me_cache.items()):
                if now - timestamp > self._get_me_cache_ttl * 2:  # 2x TTL = stale
                    stale_users.append(user_id)

            # Clean closed circuits that have expired
            for user_id, circuit_open_at in list(self._get_me_circuit_open.items()):
                if now - circuit_open_at > 3600:  # 1 hour: circuit can reset
                    del self._get_me_circuit_open[user_id]
                    stale_users.append(user_id)

            # Remove stale user tracking
            for user_id in stale_users:
                self._get_me_cache.pop(user_id, None)
                self._get_me_failure_count.pop(user_id, None)

            if stale_users:
                logger.info("GetMeErrorRecovery.cleanup: cleaned up tracking for %d users", len(stale_users))

        except Exception as e:
            logger.warning("GetMeErrorRecovery.cleanup error: %s", e)

    def clear(self) -> None:
        """Clear all tracking data on shutdown."""
        self._get_me_cache.clear()
        self._get_me_failure_count.clear()
        self._get_me_circuit_open.clear()
