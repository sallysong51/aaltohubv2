"""
External Reference Discovery

Extracts and enqueues external URLs and Telegram links from messages.
Includes blacklist filtering and duplicate detection.
"""

import re
from typing import List, Dict, Tuple
from datetime import datetime, timedelta
import logging
import sentry_sdk

from app.database import db

logger = logging.getLogger(__name__)


class ReferenceDiscovery:
    """
    Extract and enqueue external references from messages.

    Features:
    - URL extraction with blacklist checking
    - t.me link extraction
    - Duplicate detection
    - Async enqueueing to scraping/join queues
    """

    # Regex patterns
    URL_PATTERN = re.compile(
        r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b[-a-zA-Z0-9()@:%_\+.~#?&/=]*'
    )
    TELEGRAM_LINK_PATTERN = re.compile(
        r't\.me/([a-zA-Z0-9_]+)'
    )

    def __init__(self):
        """Initialize reference discovery with blacklist caching."""
        self._blacklist_cache: set[str] = set()
        self._last_blacklist_refresh = datetime.now()
        self._refresh_interval = timedelta(hours=1)

    async def discover_and_enqueue(self, message_id: int, text: str) -> Dict:
        """
        Extract references from message text and enqueue for processing.

        Args:
            message_id: Message ID
            text: Message text to parse

        Returns:
            Dict with:
                - web_urls: List of discovered web URLs
                - telegram_links: List of discovered t.me links
                - blacklisted: List of blacklisted URLs
        """
        try:
            # Refresh blacklist cache if stale
            await self._maybe_refresh_blacklist()

            # Extract references
            web_urls = self._extract_web_urls(text)
            telegram_links = self._extract_telegram_links(text)

            # Filter blacklisted
            filtered_urls, blacklisted_urls = self._filter_blacklist(web_urls)
            filtered_tg, blacklisted_tg = self._filter_blacklist(telegram_links)

            # Enqueue for processing
            await self._enqueue_web_urls(message_id, filtered_urls)
            await self._enqueue_telegram_links(message_id, filtered_tg)

            result = {
                "web_urls": filtered_urls,
                "telegram_links": filtered_tg,
                "blacklisted": blacklisted_urls + blacklisted_tg
            }

            if filtered_urls or filtered_tg:
                logger.info(
                    f"Discovered {len(filtered_urls)} URLs and {len(filtered_tg)} t.me links "
                    f"in message {message_id}"
                )

            return result

        except Exception as e:
            logger.error(f"Error discovering references in message {message_id}: {e}")
            sentry_sdk.capture_exception(e)
            return {"web_urls": [], "telegram_links": [], "blacklisted": []}

    def _extract_web_urls(self, text: str) -> List[str]:
        """
        Extract all HTTP(S) URLs from text.

        Args:
            text: Message text

        Returns:
            List of URLs (excluding t.me URLs)
        """
        urls = self.URL_PATTERN.findall(text)
        # Exclude t.me URLs (handled separately)
        return [url for url in urls if 't.me' not in url.lower()]

    def _extract_telegram_links(self, text: str) -> List[str]:
        """
        Extract all t.me/* links from text.

        Args:
            text: Message text

        Returns:
            List of t.me links as full URLs
        """
        matches = self.TELEGRAM_LINK_PATTERN.findall(text)
        return [f"https://t.me/{username}" for username in matches]

    async def _maybe_refresh_blacklist(self) -> None:
        """Refresh blacklist cache from DB if stale."""
        if datetime.now() - self._last_blacklist_refresh > self._refresh_interval:
            try:
                async with db.pool.acquire() as conn:
                    rows = await conn.fetch("SELECT pattern FROM crawl_blacklist")
                    self._blacklist_cache = {row["pattern"] for row in rows}
                    self._last_blacklist_refresh = datetime.now()
                    logger.debug(f"Refreshed blacklist cache: {len(self._blacklist_cache)} patterns")
            except Exception as e:
                logger.error(f"Failed to refresh blacklist cache: {e}")
                sentry_sdk.capture_exception(e)

    def _filter_blacklist(self, urls: List[str]) -> Tuple[List[str], List[str]]:
        """
        Filter URLs against blacklist patterns.

        Args:
            urls: List of URLs to filter

        Returns:
            Tuple of (filtered_urls, blacklisted_urls)
        """
        filtered = []
        blacklisted = []

        for url in urls:
            url_lower = url.lower()
            if any(pattern.lower() in url_lower for pattern in self._blacklist_cache):
                blacklisted.append(url)
                logger.debug(f"Blacklisted URL: {url}")
            else:
                filtered.append(url)

        return filtered, blacklisted

    async def _enqueue_web_urls(self, message_id: int, urls: List[str]) -> None:
        """
        Insert web URLs into external_references and scraping_queue.

        Args:
            message_id: Source message ID
            urls: List of web URLs to enqueue
        """
        if not urls:
            return

        try:
            async with db.pool.acquire() as conn:
                for url in urls:
                    # Check if already exists
                    existing = await conn.fetchval("""
                        SELECT id FROM external_references
                        WHERE message_id = $1 AND url = $2
                    """, message_id, url)

                    if existing:
                        logger.debug(f"URL already exists: {url}")
                        continue

                    # Insert into external_references
                    ref_id = await conn.fetchval("""
                        INSERT INTO external_references
                        (message_id, reference_type, url)
                        VALUES ($1, 'web_url', $2)
                        RETURNING id
                    """, message_id, url)

                    # Insert into scraping_queue
                    await conn.execute("""
                        INSERT INTO scraping_queue (reference_id, url)
                        VALUES ($1, $2)
                    """, ref_id, url)

                    logger.debug(f"Enqueued web URL for scraping: {url}")

        except Exception as e:
            logger.error(f"Error enqueuing web URLs: {e}")
            sentry_sdk.capture_exception(e)

    async def _enqueue_telegram_links(self, message_id: int, links: List[str]) -> None:
        """
        Insert t.me links into external_references and telegram_join_queue.

        Args:
            message_id: Source message ID
            links: List of t.me links to enqueue
        """
        if not links:
            return

        try:
            async with db.pool.acquire() as conn:
                for link in links:
                    # Check if already exists
                    existing = await conn.fetchval("""
                        SELECT id FROM external_references
                        WHERE message_id = $1 AND url = $2
                    """, message_id, link)

                    if existing:
                        logger.debug(f"Telegram link already exists: {link}")
                        continue

                    # Insert into external_references
                    ref_id = await conn.fetchval("""
                        INSERT INTO external_references
                        (message_id, reference_type, url)
                        VALUES ($1, 'telegram_link', $2)
                        RETURNING id
                    """, message_id, link)

                    # Insert into telegram_join_queue
                    await conn.execute("""
                        INSERT INTO telegram_join_queue (reference_id, telegram_link)
                        VALUES ($1, $2)
                    """, ref_id, link)

                    logger.debug(f"Enqueued Telegram link for auto-join: {link}")

        except Exception as e:
            logger.error(f"Error enqueuing Telegram links: {e}")
            sentry_sdk.capture_exception(e)

    def get_stats(self) -> Dict:
        """
        Get current stats.

        Returns:
            Dict with blacklist cache size and last refresh time
        """
        return {
            "blacklist_size": len(self._blacklist_cache),
            "last_blacklist_refresh": self._last_blacklist_refresh.isoformat()
        }
