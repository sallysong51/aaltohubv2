"""Message Handling Metrics — Per-group counters with sampling for observability.

Phase 2B: Logging Optimization & Metrics Enhancement.

Tracks:
- Messages handled per group
- Messages skipped per group (with sampling to reduce log spam)
- Skip reasons (why events rejected)
- Aggregated metrics for dashboard visibility
"""
import logging
from typing import Callable

logger = logging.getLogger(__name__)


class MessageMetrics:
    """Track message handling and skipping with per-group visibility.

    Usage:
        metrics = MessageMetrics(get_group_title_func)
        metrics.track_handled(group_id)
        metrics.track_skipped(group_id, "not_assigned")

        # Aggregate for dashboard
        summary = metrics.get_summary()
    """

    def __init__(self, get_group_title: Callable[[int], str]):
        """Initialize message metrics.

        Args:
            get_group_title: Function to get group title from group_id
        """
        self._get_group_title = get_group_title

        # Per-group message counters
        self._messages_handled: dict[int, int] = {}  # group_id -> count
        self._messages_skipped: dict[int, int] = {}  # group_id -> count
        self._skip_reasons: dict[int, dict[str, int]] = {}  # group_id -> {reason: count}

        # Sampling: log every Nth skipped message to avoid log spam
        self._skipped_since_last_log: dict[int, int] = {}  # group_id -> count since last log
        self._skip_log_interval = 100  # Log every 100 skipped messages per group

    def track_handled(self, group_id: int) -> None:
        """Track a handled message for per-group metrics.

        Args:
            group_id: Telegram group ID
        """
        self._messages_handled[group_id] = self._messages_handled.get(group_id, 0) + 1
        # Reset skipped counter when we get a handled message (shows activity)
        self._skipped_since_last_log[group_id] = 0

    def track_skipped(self, group_id: int, reason: str) -> None:
        """Track a skipped message with sampling to avoid log spam.

        Logs every Nth skipped message (configurable via _skip_log_interval).
        Tracks reason for skipping for debugging.

        Args:
            group_id: Telegram group ID
            reason: Why message was skipped (e.g., 'not_in_map', 'not_assigned', 'not_enabled')
        """
        self._messages_skipped[group_id] = self._messages_skipped.get(group_id, 0) + 1
        self._skipped_since_last_log[group_id] = self._skipped_since_last_log.get(group_id, 0) + 1

        # Track skip reason
        if group_id not in self._skip_reasons:
            self._skip_reasons[group_id] = {}
        self._skip_reasons[group_id][reason] = self._skip_reasons[group_id].get(reason, 0) + 1

        # Log with sampling: every Nth skipped message per group
        if self._skipped_since_last_log[group_id] >= self._skip_log_interval:
            group_title = self._get_group_title(group_id)
            skipped_count = self._messages_skipped[group_id]
            reasons_str = ", ".join(
                f"{r}={c}" for r, c in sorted(self._skip_reasons[group_id].items())
            )
            logger.debug(
                "[SKIP] %s: skipped %d messages (reasons: %s)",
                group_title,
                skipped_count,
                reasons_str,
            )
            self._skipped_since_last_log[group_id] = 0

    def get_summary(self) -> dict:
        """Get aggregated metrics for status/dashboard.

        Returns:
            Dict with keys:
            - messages_handled: total handled count
            - messages_skipped: total skipped count
            - skip_reasons: aggregated skip reasons across all groups
        """
        total_handled = sum(self._messages_handled.values())
        total_skipped = sum(self._messages_skipped.values())

        # Aggregate skip reasons across all groups
        aggregated_skip_reasons: dict[str, int] = {}
        for group_reasons in self._skip_reasons.values():
            for reason, count in group_reasons.items():
                aggregated_skip_reasons[reason] = aggregated_skip_reasons.get(reason, 0) + count

        return {
            "messages_handled": total_handled,
            "messages_skipped": total_skipped,
            "skip_reasons": aggregated_skip_reasons,
        }

    def get_per_group_metrics(self, group_id: int) -> dict:
        """Get metrics for a specific group.

        Args:
            group_id: Telegram group ID

        Returns:
            Dict with handled, skipped, and reasons for this group
        """
        return {
            "group_id": group_id,
            "group_title": self._get_group_title(group_id),
            "handled": self._messages_handled.get(group_id, 0),
            "skipped": self._messages_skipped.get(group_id, 0),
            "skip_reasons": self._skip_reasons.get(group_id, {}),
        }

    def clear(self) -> None:
        """Clear all metrics on shutdown."""
        self._messages_handled.clear()
        self._messages_skipped.clear()
        self._skip_reasons.clear()
        self._skipped_since_last_log.clear()
