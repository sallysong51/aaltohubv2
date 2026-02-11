"""Metrics Module — Prometheus metrics + MessageMetrics class.

Combines:
1. Prometheus metrics for /metrics endpoint (Phase 21)
2. MessageMetrics class for per-group tracking (Phase 32D)
"""
import logging
from typing import Callable

logger = logging.getLogger(__name__)


# ============================================================================
# Prometheus Metrics (Phase 21)
# ============================================================================

class _Counter:
    """Simple Prometheus Counter with labels."""
    def __init__(self, name: str, description: str, labels: list[str]):
        self.name = name
        self.description = description
        self.labels = labels
        self._values: dict[tuple, int] = {}

    def inc(self, label_values: tuple) -> None:
        """Increment counter for given label values."""
        self._values[label_values] = self._values.get(label_values, 0) + 1

    def render(self) -> str:
        """Render in Prometheus exposition format."""
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} counter",
        ]
        for label_values, value in sorted(self._values.items()):
            label_str = ",".join(
                f'{label}="{val}"' for label, val in zip(self.labels, label_values)
            )
            lines.append(f"{self.name}{{{label_str}}} {value}")
        return "\n".join(lines)


class _Gauge:
    """Simple Prometheus Gauge."""
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._value = 0

    def set(self, value: int) -> None:
        """Set gauge value."""
        self._value = value

    def render(self) -> str:
        """Render in Prometheus exposition format."""
        return f"# HELP {self.name} {self.description}\n# TYPE {self.name} gauge\n{self.name} {self._value}"


class _Metrics:
    """Prometheus metrics collector."""
    def __init__(self):
        self.http_requests_total = _Counter(
            "http_requests_total",
            "Total HTTP requests",
            ["method", "path", "status_code"]
        )
        self.messages_total = _Gauge("messages_total", "Total messages received by crawler")
        self.crawler_groups_active = _Gauge("crawler_groups_active", "Active groups in crawler")
        self.queue_size = _Gauge("queue_size", "Crawler queue size")
        self.sse_connections = _Gauge("sse_connections", "Active SSE connections")

    def render(self) -> str:
        """Render all metrics in Prometheus format."""
        return "\n\n".join([
            self.http_requests_total.render(),
            self.messages_total.render(),
            self.crawler_groups_active.render(),
            self.queue_size.render(),
            self.sse_connections.render(),
        ])


# Global metrics instance
metrics = _Metrics()


# ============================================================================
# MessageMetrics Class (Phase 32D)
# ============================================================================


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


class GapFillMetrics:
    """Track gap-fill effectiveness and SLA compliance per group.

    Provides real-time visibility into which groups are at risk of
    violating the 3-hour message recovery SLA.
    """

    def __init__(self):
        self._last_gap_fill: dict[int, float] = {}  # group_id -> timestamp
        self._messages_recovered: dict[int, int] = {}  # group_id -> count
        self._failures: dict[int, int] = {}  # group_id -> consecutive failures

    def record_gap_fill_success(self, group_id: int, messages_found: int) -> None:
        """Record successful gap-fill for a group."""
        import time
        self._last_gap_fill[group_id] = time.time()
        self._messages_recovered[group_id] = self._messages_recovered.get(group_id, 0) + messages_found
        self._failures[group_id] = 0  # Reset failure count on success

    def record_gap_fill_failure(self, group_id: int, reason: str) -> None:
        """Record failed gap-fill (FloodWait, timeout, etc)."""
        import logging
        self._failures[group_id] = self._failures.get(group_id, 0) + 1
        logger = logging.getLogger(__name__)
        logger.warning("[GAP-FILL-METRICS] Group %d failure: %s (consecutive=%d)",
                       group_id, reason, self._failures[group_id])

    def get_groups_exceeding_sla(self, sla_hours: float = 2.5) -> list[dict]:
        """Return groups that haven't had successful gap-fill in SLA window.

        Args:
            sla_hours: Alert threshold (default 2.5h = 30min before 3h breach)

        Returns:
            List of dicts with group_id, hours_since_last_fill, consecutive_failures
        """
        import time
        now = time.time()
        threshold = now - (sla_hours * 3600)

        at_risk = []
        for group_id, last_fill in self._last_gap_fill.items():
            if last_fill < threshold:
                hours_since = (now - last_fill) / 3600
                at_risk.append({
                    "group_id": group_id,
                    "hours_since_last_fill": round(hours_since, 2),
                    "consecutive_failures": self._failures.get(group_id, 0),
                })

        return sorted(at_risk, key=lambda x: x["hours_since_last_fill"], reverse=True)

    def clear(self) -> None:
        """Clear all metrics on shutdown."""
        self._last_gap_fill.clear()
        self._messages_recovered.clear()
        self._failures.clear()
