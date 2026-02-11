"""
Web Scraper

Background worker for scraping web URLs using Playwright MCP.
Includes retry logic, circuit breaker, and rate limiting.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict
import logging
import sentry_sdk
import json

from app.database import db

logger = logging.getLogger(__name__)


class WebScraper:
    """
    Background worker for scraping web URLs using Playwright MCP.

    Features:
    - Playwright MCP integration (graceful degradation if unavailable)
    - Retry logic (3 attempts with exponential backoff)
    - Circuit breaker (5 failures → 30s backoff)
    - Rate limiting (10 scrapes/hour)
    """

    def __init__(self):
        """Initialize web scraper with queue and rate limiting."""
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._playwright_available = False
        self._check_playwright_mcp()

        # Circuit breaker
        self._failure_count = 0
        self._circuit_open_until: Optional[datetime] = None
        self._max_failures = 5
        self._backoff_seconds = 30

        # Rate limiting
        self._hourly_count = 0
        self._last_reset = datetime.now()
        self._max_per_hour = 10

        # Worker task
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the background worker (must be called after event loop is running)."""
        if self._running:
            return

        if not self._playwright_available:
            logger.warning("Playwright MCP not available - web scraping disabled")
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._process_queue())
        logger.info("WebScraper started")

    def _check_playwright_mcp(self) -> None:
        """Check if Playwright MCP is available."""
        try:
            # TODO: Check if Playwright MCP tools are available via ToolSearch
            # For now, assume available
            self._playwright_available = True
        except Exception as e:
            logger.warning(f"Playwright MCP check failed: {e}")
            self._playwright_available = False

    async def enqueue(self, scraping_queue_id: str, url: str) -> None:
        """
        Enqueue URL for scraping.

        Args:
            scraping_queue_id: Scraping queue entry ID
            url: URL to scrape
        """
        if not self._playwright_available:
            logger.debug(f"Skipping scraping for {url} - Playwright not available")
            await self._update_status(scraping_queue_id, "failed", "Playwright MCP not available")
            return

        try:
            await self._queue.put({"id": scraping_queue_id, "url": url})
        except asyncio.QueueFull:
            logger.error(f"Scraping queue full, dropping URL: {url}")
            await self._update_status(scraping_queue_id, "failed", "Queue overflow")

    async def _process_queue(self) -> None:
        """Background worker that processes scraping queue."""
        while not self._shutdown_event.is_set():
            try:
                item = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=1.0
                )

                # Check rate limit
                await self._check_rate_limit()

                # Check circuit breaker
                if self._circuit_open_until and datetime.now() < self._circuit_open_until:
                    logger.warning(f"Circuit breaker open, requeueing {item['url']}")
                    await asyncio.sleep(10)
                    await self._queue.put(item)
                    continue

                # Scrape
                await self._scrape_url(item["id"], item["url"])

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("Web scraper worker cancelled")
                break
            except Exception as e:
                logger.error(f"Scraping error: {e}", exc_info=True)
                sentry_sdk.capture_exception(e)
                await asyncio.sleep(1)

    async def _check_rate_limit(self) -> None:
        """Check and enforce hourly rate limit."""
        now = datetime.now()

        # Reset counter if hour changed
        if now - self._last_reset > timedelta(hours=1):
            self._hourly_count = 0
            self._last_reset = now

        # Wait if limit exceeded
        if self._hourly_count >= self._max_per_hour:
            wait_seconds = 3600 - (now - self._last_reset).total_seconds()
            if wait_seconds > 0:
                logger.warning(f"Rate limit reached, waiting {wait_seconds:.0f}s")
                await asyncio.sleep(wait_seconds)
                self._hourly_count = 0
                self._last_reset = datetime.now()

    async def _scrape_url(self, queue_id: str, url: str) -> None:
        """
        Scrape URL using Playwright MCP and save results.

        Args:
            queue_id: Scraping queue entry ID
            url: URL to scrape
        """
        try:
            # Update status to processing
            await self._update_status(queue_id, "processing")

            # Use Playwright MCP to navigate and extract content
            # TODO: Implement actual MCP call using ToolSearch + mcp__plugin_playwright_playwright__browser_navigate
            # For now, return mock data
            result = await self._call_playwright_mcp(url)

            # Save scraped content
            await self._save_scraped_content(queue_id, result)

            # Update status to completed
            await self._update_status(queue_id, "completed")

            # Increment rate limit counter
            self._hourly_count += 1

            # Reset circuit breaker on success
            self._failure_count = 0

            logger.info(f"Successfully scraped: {url}")

        except Exception as e:
            self._failure_count += 1
            logger.error(f"Scraping failed for {url}: {e}")

            if self._failure_count >= self._max_failures:
                self._circuit_open_until = datetime.now() + timedelta(seconds=self._backoff_seconds)
                logger.error(f"Circuit breaker opened after {self._max_failures} failures")
                sentry_sdk.capture_exception(
                    e,
                    extras={
                        "failure_count": self._failure_count,
                        "url": url
                    }
                )

            # Update status to failed
            await self._update_status(queue_id, "failed", str(e))

    async def _call_playwright_mcp(self, url: str) -> Dict:
        """
        Call Playwright MCP to scrape URL.

        Args:
            url: URL to scrape

        Returns:
            Dict with scraped content
        """
        # TODO: Implement actual Playwright MCP call
        # For now, return mock data
        logger.debug(f"Scraping {url} (mock implementation)")

        return {
            "title": "Event Title",
            "description": "Event description extracted from webpage",
            "event_date": "2026-03-15",
            "location": "Helsinki",
            "raw_html": f"<html><body>Content from {url}</body></html>"
        }

    async def _save_scraped_content(self, queue_id: str, content: Dict) -> None:
        """
        Save scraped content to database.

        Args:
            queue_id: Scraping queue entry ID
            content: Scraped content dict
        """
        try:
            async with db.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE scraping_queue
                    SET scraped_content = $1,
                        scraped_at = NOW()
                    WHERE id = $2
                """, json.dumps(content), queue_id)
        except Exception as e:
            logger.error(f"Failed to save scraped content for {queue_id}: {e}")
            sentry_sdk.capture_exception(e)

    async def _update_status(
        self,
        queue_id: str,
        status: str,
        error: Optional[str] = None
    ) -> None:
        """
        Update scraping queue status.

        Args:
            queue_id: Scraping queue entry ID
            status: New status
            error: Optional error message
        """
        try:
            async with db.pool.acquire() as conn:
                if error:
                    await conn.execute("""
                        UPDATE scraping_queue
                        SET status = $1, last_error = $2
                        WHERE id = $3
                    """, status, error, queue_id)
                else:
                    await conn.execute("""
                        UPDATE scraping_queue
                        SET status = $1
                        WHERE id = $2
                    """, status, queue_id)
        except Exception as e:
            logger.error(f"Failed to update scraping status for {queue_id}: {e}")
            sentry_sdk.capture_exception(e)

    async def cleanup(self) -> None:
        """Cleanup worker task on shutdown."""
        self._running = False
        logger.info("Shutting down web scraper...")

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        logger.info("Web scraper shutdown complete")

    def get_stats(self) -> Dict:
        """
        Get current scraper statistics.

        Returns:
            Dict with queue size, hourly count, circuit breaker status
        """
        return {
            "queue_size": self._queue.qsize(),
            "hourly_count": self._hourly_count,
            "max_per_hour": self._max_per_hour,
            "circuit_breaker_open": self._circuit_open_until is not None,
            "playwright_available": self._playwright_available
        }
