"""Connection Health Tracker for Smart Auto-Join Account Selection.

This module provides intelligent Telegram connection selection for the auto-join feature.
It tracks per-connection join history, FloodWait penalties, and failure streaks to
calculate a "health score" for each connection. Lower scores indicate healthier connections.

Scoring Algorithm:
    score = (
        flood_wait_penalty +      # 1000 if active FloodWait, 0 otherwise
        recent_join_penalty +     # joins_last_hour * 100
        daily_limit_penalty +     # (joins_today / 10) * 500
        failure_streak_penalty    # consecutive_failures * 200
    )

Example Usage:
    tracker = ConnectionHealthTracker(db)
    await tracker.sync_flood_wait_from_crawler(crawler_client)

    # Calculate score for each connection
    for conn in connections:
        score = tracker.calculate_connection_score(conn.telegram_user_id)
        print(f"Connection {conn.id}: score={score}")

    # Record join attempt
    tracker.record_join_attempt(
        telegram_user_id=123456789,
        connection_id=UUID("..."),
        success=True,
        error_type=None
    )
"""

import time
import logging
from typing import Dict, List, Tuple, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class ConnectionHealthTracker:
    """Tracks health metrics for Telegram connections to enable smart account selection.

    This class maintains in-memory state about each connection's recent join activity,
    FloodWait penalties, and failure patterns. It provides real-time scoring to select
    the safest connection for auto-join operations.

    Attributes:
        _join_history: Maps telegram_user_id → list of join timestamps (monotonic time)
        _failure_count: Maps telegram_user_id → count of consecutive failures
        _flood_wait_until: Maps telegram_user_id → expiry timestamp (monotonic time)
        _connection_id_map: Maps telegram_user_id → connection_id (UUID string)
    """

    # Penalty weight constants
    FLOOD_WAIT_PENALTY = 1000  # Active FloodWait = unusable
    HOURLY_JOIN_PENALTY = 100  # Per join in last hour
    DAILY_LIMIT_PENALTY_RATE = 500 / 10  # (joins_today / 10) * 500
    FAILURE_STREAK_PENALTY = 200  # Per consecutive failure

    # Rate limits (Telegram's approximate limits)
    HOURLY_LIMIT = 3  # Conservative: 3 joins per hour
    DAILY_LIMIT = 10  # Conservative: 10 joins per day

    # Scoring thresholds
    UNHEALTHY_SCORE_THRESHOLD = 800  # Above this = all connections unhealthy

    # History retention
    HISTORY_RETENTION_SECONDS = 86400  # 24 hours

    def __init__(self):
        """Initialize the connection health tracker with empty state."""
        # telegram_user_id → list of join timestamps (monotonic time, sorted ascending)
        self._join_history: Dict[int, List[float]] = {}

        # telegram_user_id → consecutive failure count
        self._failure_count: Dict[int, int] = {}

        # telegram_user_id → FloodWait expiry timestamp (monotonic time)
        # Synced from live_crawler via sync_flood_wait_from_crawler()
        self._flood_wait_until: Dict[int, float] = {}

        # telegram_user_id → connection_id (UUID string)
        # Used to map scores back to connection IDs
        self._connection_id_map: Dict[int, str] = {}

        logger.info("ConnectionHealthTracker initialized")

    def register_connection(self, telegram_user_id: int, connection_id: UUID) -> None:
        """Register a connection for tracking.

        Args:
            telegram_user_id: Telegram user ID from client.get_me()
            connection_id: UUID of the telegram_connection record
        """
        self._connection_id_map[telegram_user_id] = str(connection_id)
        if telegram_user_id not in self._join_history:
            self._join_history[telegram_user_id] = []
        if telegram_user_id not in self._failure_count:
            self._failure_count[telegram_user_id] = 0

        logger.debug(
            f"Registered connection: user_id={telegram_user_id}, "
            f"connection_id={connection_id}"
        )

    def sync_flood_wait_penalties(
        self, flood_wait_status: Dict[int, float]
    ) -> None:
        """Sync FloodWait penalties from live_crawler.

        Args:
            flood_wait_status: Dict mapping telegram_user_id → expiry timestamp (monotonic)
        """
        self._flood_wait_until = flood_wait_status.copy()
        active_count = sum(
            1 for expiry in flood_wait_status.values()
            if time.monotonic() < expiry
        )
        logger.debug(
            f"Synced FloodWait penalties: {len(flood_wait_status)} total, "
            f"{active_count} currently active"
        )

    def is_flood_wait_active(self, telegram_user_id: int) -> bool:
        """Check if a connection has an active FloodWait penalty.

        Args:
            telegram_user_id: Telegram user ID to check

        Returns:
            True if FloodWait penalty is still active, False otherwise
        """
        expiry = self._flood_wait_until.get(telegram_user_id, 0)
        return time.monotonic() < expiry

    def get_joins_last_hour(self, telegram_user_id: int) -> int:
        """Count join attempts in the last 60 minutes.

        Args:
            telegram_user_id: Telegram user ID to check

        Returns:
            Number of join attempts in the last hour
        """
        now = time.monotonic()
        cutoff = now - 3600  # 1 hour ago

        history = self._join_history.get(telegram_user_id, [])
        return sum(1 for timestamp in history if timestamp >= cutoff)

    def get_joins_today(self, telegram_user_id: int) -> int:
        """Count join attempts since midnight UTC (approximation using 24h window).

        Note: This uses a 24-hour rolling window from monotonic time, not actual
        calendar day. This is intentional to avoid timezone complexities and provides
        conservative rate limiting.

        Args:
            telegram_user_id: Telegram user ID to check

        Returns:
            Number of join attempts in the last 24 hours
        """
        now = time.monotonic()
        cutoff = now - 86400  # 24 hours ago

        history = self._join_history.get(telegram_user_id, [])
        return sum(1 for timestamp in history if timestamp >= cutoff)

    def get_consecutive_failures(self, telegram_user_id: int) -> int:
        """Get the count of consecutive failed join attempts.

        Args:
            telegram_user_id: Telegram user ID to check

        Returns:
            Number of consecutive failures (reset on success)
        """
        return self._failure_count.get(telegram_user_id, 0)

    def calculate_connection_score(self, telegram_user_id: int) -> int:
        """Calculate health score for a connection (lower = healthier).

        Scoring formula:
            score = (
                flood_wait_penalty +      # 1000 if active FloodWait, 0 otherwise
                recent_join_penalty +     # joins_last_hour * 100
                daily_limit_penalty +     # (joins_today / 10) * 500
                failure_streak_penalty    # consecutive_failures * 200
            )

        Args:
            telegram_user_id: Telegram user ID to score

        Returns:
            Health score (0 = perfect, higher = worse)
        """
        score = 0

        # FloodWait penalty (binary: 1000 or 0)
        if self.is_flood_wait_active(telegram_user_id):
            score += self.FLOOD_WAIT_PENALTY

        # Hourly rate limit penalty
        hourly_joins = self.get_joins_last_hour(telegram_user_id)
        score += hourly_joins * self.HOURLY_JOIN_PENALTY

        # Daily rate limit penalty (scaled)
        daily_joins = self.get_joins_today(telegram_user_id)
        score += int((daily_joins / 10) * 500)

        # Consecutive failure penalty
        failures = self.get_consecutive_failures(telegram_user_id)
        score += failures * self.FAILURE_STREAK_PENALTY

        logger.debug(
            f"Score for user {telegram_user_id}: {score} "
            f"(flood={self.is_flood_wait_active(telegram_user_id)}, "
            f"hourly={hourly_joins}, daily={daily_joins}, failures={failures})"
        )

        return score

    def record_join_attempt(
        self,
        telegram_user_id: int,
        connection_id: UUID,
        success: bool,
        error_type: Optional[str] = None
    ) -> None:
        """Record a join attempt for rate limiting and failure tracking.

        Args:
            telegram_user_id: Telegram user ID that attempted the join
            connection_id: UUID of the connection used
            success: True if join succeeded, False if failed
            error_type: Error category if failed (e.g., 'flood_wait', 'invite_expired')
        """
        now = time.monotonic()

        # Ensure connection is registered
        if telegram_user_id not in self._connection_id_map:
            self.register_connection(telegram_user_id, connection_id)

        # Record timestamp for rate limiting
        if telegram_user_id not in self._join_history:
            self._join_history[telegram_user_id] = []
        self._join_history[telegram_user_id].append(now)

        # Update failure streak
        if success:
            # Reset failure count on success
            self._failure_count[telegram_user_id] = 0
            logger.info(
                f"Recorded successful join: user_id={telegram_user_id}, "
                f"connection_id={connection_id}"
            )
        else:
            # Increment failure count
            self._failure_count[telegram_user_id] = (
                self._failure_count.get(telegram_user_id, 0) + 1
            )
            logger.warning(
                f"Recorded failed join: user_id={telegram_user_id}, "
                f"connection_id={connection_id}, error={error_type}, "
                f"consecutive_failures={self._failure_count[telegram_user_id]}"
            )

    def cleanup_old_history(self) -> None:
        """Remove join history older than HISTORY_RETENTION_SECONDS (24 hours).

        This prevents unbounded memory growth. Should be called periodically
        (e.g., every 1 hour) by a background task.
        """
        now = time.monotonic()
        cutoff = now - self.HISTORY_RETENTION_SECONDS

        total_removed = 0
        for user_id, history in list(self._join_history.items()):
            # Filter out timestamps older than cutoff
            old_count = len(history)
            self._join_history[user_id] = [
                timestamp for timestamp in history if timestamp >= cutoff
            ]
            new_count = len(self._join_history[user_id])
            total_removed += (old_count - new_count)

            # Remove empty history entries
            if not self._join_history[user_id]:
                del self._join_history[user_id]

        # Clean up stale FloodWait entries (older than 1 hour)
        flood_cutoff = now - 3600
        expired_floods = [
            user_id for user_id, expiry in self._flood_wait_until.items()
            if expiry < flood_cutoff
        ]
        for user_id in expired_floods:
            del self._flood_wait_until[user_id]

        if total_removed > 0 or expired_floods:
            logger.info(
                f"Cleaned up history: removed {total_removed} old join records, "
                f"{len(expired_floods)} expired FloodWait entries"
            )

    def get_best_connection(
        self, candidate_user_ids: List[int]
    ) -> Tuple[Optional[int], int, Dict[int, int]]:
        """Select the best connection from a list of candidates.

        Args:
            candidate_user_ids: List of telegram_user_ids to choose from

        Returns:
            Tuple of (best_user_id, best_score, all_scores_dict)
            best_user_id is None if all connections are unhealthy (score > threshold)
        """
        if not candidate_user_ids:
            logger.warning("No candidate connections provided")
            return None, 0, {}

        # Calculate scores for all candidates
        scores = {
            user_id: self.calculate_connection_score(user_id)
            for user_id in candidate_user_ids
        }

        # Sort by score (ascending = better)
        sorted_candidates = sorted(scores.items(), key=lambda x: x[1])
        best_user_id, best_score = sorted_candidates[0]

        # Check if best is still unhealthy
        if best_score > self.UNHEALTHY_SCORE_THRESHOLD:
            logger.warning(
                f"All {len(candidate_user_ids)} connections are unhealthy. "
                f"Best score: {best_score} (threshold: {self.UNHEALTHY_SCORE_THRESHOLD})"
            )
            return None, best_score, scores

        logger.info(
            f"Selected best connection: user_id={best_user_id}, score={best_score} "
            f"(out of {len(candidate_user_ids)} candidates)"
        )
        return best_user_id, best_score, scores

    def estimate_wait_time(self, telegram_user_id: int) -> int:
        """Estimate seconds until a connection becomes healthy again.

        Args:
            telegram_user_id: Telegram user ID to check

        Returns:
            Estimated wait time in seconds (0 if already healthy)
        """
        now = time.monotonic()
        wait_time = 0

        # FloodWait is the primary blocker
        flood_expiry = self._flood_wait_until.get(telegram_user_id, 0)
        if flood_expiry > now:
            wait_time = max(wait_time, int(flood_expiry - now))

        # If no FloodWait, estimate based on hourly rate limit
        if wait_time == 0:
            hourly_joins = self.get_joins_last_hour(telegram_user_id)
            if hourly_joins >= self.HOURLY_LIMIT:
                # Need to wait until oldest join in last hour expires
                history = self._join_history.get(telegram_user_id, [])
                if history:
                    oldest_in_hour = min(
                        t for t in history if t >= (now - 3600)
                    )
                    wait_time = max(wait_time, int((oldest_in_hour + 3600) - now))

        return wait_time

    def get_status(self) -> Dict:
        """Get current tracker status for debugging/monitoring.

        Returns:
            Dict with tracker statistics
        """
        now = time.monotonic()
        active_floods = sum(
            1 for expiry in self._flood_wait_until.values()
            if expiry > now
        )

        return {
            "tracked_connections": len(self._connection_id_map),
            "active_flood_waits": active_floods,
            "total_join_history_entries": sum(
                len(history) for history in self._join_history.values()
            ),
            "connections_with_failures": sum(
                1 for count in self._failure_count.values() if count > 0
            ),
        }

    def clear(self) -> None:
        """Clear all tracking data (for shutdown or testing)."""
        self._join_history.clear()
        self._failure_count.clear()
        self._flood_wait_until.clear()
        self._connection_id_map.clear()
        logger.info("ConnectionHealthTracker cleared")
