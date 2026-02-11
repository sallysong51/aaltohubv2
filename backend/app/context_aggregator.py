"""
Context Aggregator

Aggregate group context metadata for AI classification enhancement.
Includes keyword frequency, activity patterns, top senders, and membership detection.
"""

import asyncio
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List
import logging
import sentry_sdk
import json
import re

from app.database import db

logger = logging.getLogger(__name__)


class ContextAggregator:
    """
    Aggregate group context metadata for AI classification enhancement.

    Features:
    - Keyword frequency tracking (top 50)
    - Activity pattern detection (peak hours, daily avg)
    - Top sender identification (top 10)
    - Membership info detection (paid/free)
    """

    def __init__(self):
        """Initialize context aggregator with periodic update."""
        self._update_interval = timedelta(hours=6)
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the background worker (must be called after event loop is running)."""
        if self._running:
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._periodic_update())
        logger.info("ContextAggregator started")

    async def _periodic_update(self) -> None:
        """Periodically update group contexts."""
        while not self._shutdown_event.is_set():
            try:
                await self._update_all_group_contexts()
                await asyncio.sleep(self._update_interval.total_seconds())
            except asyncio.CancelledError:
                logger.info("Context aggregator worker cancelled")
                break
            except Exception as e:
                logger.error(f"Context aggregation error: {e}", exc_info=True)
                sentry_sdk.capture_exception(e)
                await asyncio.sleep(60)

    async def _update_all_group_contexts(self) -> None:
        """Update contexts for all enabled groups."""
        try:
            async with db.pool.acquire() as conn:
                groups = await conn.fetch("SELECT id FROM groups WHERE is_enabled = TRUE")

                logger.info(f"Updating context for {len(groups)} groups")

                for group in groups:
                    try:
                        await self._update_group_context(group["id"])
                    except Exception as e:
                        logger.error(f"Error updating context for group {group['id']}: {e}")
                        # Continue with other groups
                        continue

                logger.info("Context update completed for all groups")

        except Exception as e:
            logger.error(f"Failed to fetch groups for context update: {e}")
            sentry_sdk.capture_exception(e)

    async def _update_group_context(self, group_id: int) -> None:
        """
        Update context metadata for single group.

        Args:
            group_id: Telegram group ID
        """
        try:
            # Extract keywords from recent messages (last 30 days)
            keywords = await self._extract_keywords(group_id)

            # Detect activity patterns
            patterns = await self._detect_patterns(group_id)

            # Identify top senders
            top_senders = await self._get_top_senders(group_id)

            # Detect membership info
            membership_info = await self._detect_membership(group_id)

            # Save to group_contexts
            async with db.pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO group_contexts
                    (group_id, keywords, activity_patterns, top_senders, membership_info)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (group_id)
                    DO UPDATE SET
                        keywords = $2,
                        activity_patterns = $3,
                        top_senders = $4,
                        membership_info = $5,
                        last_updated = NOW()
                """, group_id, json.dumps(keywords), json.dumps(patterns),
                    json.dumps(top_senders), json.dumps(membership_info))

            logger.debug(f"Updated context for group {group_id}")

        except Exception as e:
            logger.error(f"Error updating context for group {group_id}: {e}")
            sentry_sdk.capture_exception(e)

    async def _extract_keywords(self, group_id: int) -> Dict[str, int]:
        """
        Extract keywords from recent messages.

        Args:
            group_id: Telegram group ID

        Returns:
            Dict with top 50 keywords and their frequencies
        """
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT text FROM messages
                    WHERE group_id = $1
                      AND created_at > NOW() - INTERVAL '30 days'
                      AND text IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 1000
                """, group_id)

            # Simple keyword extraction (can be enhanced with NLP)
            counter = Counter()
            for row in rows:
                words = row["text"].lower().split()
                # Filter stop words, keep words >3 chars
                keywords = [w for w in words if len(w) > 3 and w.isalpha()]
                counter.update(keywords)

            # Return top 50 keywords
            return dict(counter.most_common(50))

        except Exception as e:
            logger.error(f"Error extracting keywords for group {group_id}: {e}")
            return {}

    async def _detect_patterns(self, group_id: int) -> Dict:
        """
        Detect activity patterns (time slots, frequency).

        Args:
            group_id: Telegram group ID

        Returns:
            Dict with peak hours and daily average
        """
        try:
            async with db.pool.acquire() as conn:
                # Get message timestamps for last 30 days
                rows = await conn.fetch("""
                    SELECT EXTRACT(HOUR FROM created_at) as hour,
                           COUNT(*) as count
                    FROM messages
                    WHERE group_id = $1
                      AND created_at > NOW() - INTERVAL '30 days'
                    GROUP BY hour
                    ORDER BY count DESC
                """, group_id)

            if not rows:
                return {"peak_hours": [], "daily_avg": 0}

            total_messages = sum(row["count"] for row in rows)
            return {
                "peak_hours": [int(row["hour"]) for row in rows[:3]],
                "daily_avg": round(total_messages / 30, 2)
            }

        except Exception as e:
            logger.error(f"Error detecting patterns for group {group_id}: {e}")
            return {"peak_hours": [], "daily_avg": 0}

    async def _get_top_senders(self, group_id: int) -> List[Dict]:
        """
        Identify top message senders.

        Args:
            group_id: Telegram group ID

        Returns:
            List of top 10 senders with message counts
        """
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT sender_id, COUNT(*) as msg_count
                    FROM messages
                    WHERE group_id = $1
                      AND created_at > NOW() - INTERVAL '30 days'
                    GROUP BY sender_id
                    ORDER BY msg_count DESC
                    LIMIT 10
                """, group_id)

            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"Error getting top senders for group {group_id}: {e}")
            return []

    async def _detect_membership(self, group_id: int) -> Dict:
        """
        Detect membership requirements from messages.

        Args:
            group_id: Telegram group ID

        Returns:
            Dict with membership detection results
        """
        try:
            async with db.pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT text FROM messages
                    WHERE group_id = $1
                      AND text ILIKE ANY(ARRAY['%member%', '%fee%', '%price%', '%euro%', '%dollar%'])
                      AND created_at > NOW() - INTERVAL '30 days'
                    ORDER BY created_at DESC
                    LIMIT 100
                """, group_id)

            # Simple pattern matching (can be enhanced with AI)
            membership = {"detected": False}

            for row in rows:
                if not row["text"]:
                    continue

                text = row["text"].lower()

                # Detect membership fee patterns
                if "member" in text and any(word in text for word in ["fee", "price", "cost"]):
                    # Extract numbers
                    numbers = re.findall(r'\d+', text)
                    if numbers:
                        membership = {
                            "detected": True,
                            "type": "paid",
                            "amount": int(numbers[0]),
                            "period": "year" if "year" in text else "month"
                        }
                        break

            return membership

        except Exception as e:
            logger.error(f"Error detecting membership for group {group_id}: {e}")
            return {"detected": False}

    async def cleanup(self) -> None:
        """Cleanup worker task on shutdown."""
        self._running = False
        logger.info("Shutting down context aggregator...")

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        logger.info("Context aggregator shutdown complete")

    def get_stats(self) -> Dict:
        """
        Get current aggregator statistics.

        Returns:
            Dict with worker status
        """
        return {
            "worker_running": self._worker_task and not self._worker_task.done(),
            "update_interval_hours": self._update_interval.total_seconds() / 3600
        }
