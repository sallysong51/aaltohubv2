"""
Prometheus-compatible metrics endpoint for AaltoHub v2.

Provides counters and gauges in Prometheus text exposition format.
No external dependencies required -- uses plain Python with thread-safe counters.

Metrics exposed:
  - aaltohub_messages_total          (counter)  Total messages processed
  - aaltohub_crawler_groups_active   (gauge)    Number of active crawler groups
  - aaltohub_queue_size              (gauge)    Current message queue size
  - aaltohub_http_requests_total     (counter)  HTTP requests by method/path/status
  - aaltohub_db_operations_total     (counter)  Database operations executed
"""

import threading
import time
from typing import Dict, Tuple


class _Counter:
    """Thread-safe monotonically increasing counter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: float = 0

    def inc(self, amount: float = 1) -> None:
        with self._lock:
            self._value += amount

    @property
    def value(self) -> float:
        with self._lock:
            return self._value


class _LabeledCounter:
    """Thread-safe counter with label dimensions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: Dict[Tuple[str, ...], float] = {}

    def inc(self, labels: Tuple[str, ...], amount: float = 1) -> None:
        with self._lock:
            self._values[labels] = self._values.get(labels, 0) + amount

    def items(self) -> list:
        with self._lock:
            return list(self._values.items())


class _Gauge:
    """Thread-safe gauge that can go up or down."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: float = 0

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1) -> None:
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1) -> None:
        with self._lock:
            self._value -= amount

    @property
    def value(self) -> float:
        with self._lock:
            return self._value


class MetricsRegistry:
    """Central registry for all application metrics."""

    def __init__(self) -> None:
        # Counters
        self.messages_total = _Counter()
        self.db_operations_total = _Counter()
        self.http_requests_total = _LabeledCounter()

        # Gauges
        self.crawler_groups_active = _Gauge()
        self.queue_size = _Gauge()

        self._start_time = time.time()

    def render(self) -> str:
        """Render all metrics in Prometheus text exposition format."""
        lines: list[str] = []

        # -- aaltohub_messages_total --
        lines.append("# HELP aaltohub_messages_total Total messages processed by the crawler.")
        lines.append("# TYPE aaltohub_messages_total counter")
        lines.append(f"aaltohub_messages_total {self.messages_total.value}")

        # -- aaltohub_crawler_groups_active --
        lines.append("# HELP aaltohub_crawler_groups_active Number of active crawler groups.")
        lines.append("# TYPE aaltohub_crawler_groups_active gauge")
        lines.append(f"aaltohub_crawler_groups_active {self.crawler_groups_active.value}")

        # -- aaltohub_queue_size --
        lines.append("# HELP aaltohub_queue_size Current message queue size.")
        lines.append("# TYPE aaltohub_queue_size gauge")
        lines.append(f"aaltohub_queue_size {self.queue_size.value}")

        # -- aaltohub_http_requests_total --
        lines.append("# HELP aaltohub_http_requests_total Total HTTP requests by method, path, and status.")
        lines.append("# TYPE aaltohub_http_requests_total counter")
        for labels, value in self.http_requests_total.items():
            method, path, status = labels
            lines.append(
                f'aaltohub_http_requests_total{{method="{method}",path="{path}",status="{status}"}} {value}'
            )

        # -- aaltohub_db_operations_total --
        lines.append("# HELP aaltohub_db_operations_total Total database operations executed.")
        lines.append("# TYPE aaltohub_db_operations_total counter")
        lines.append(f"aaltohub_db_operations_total {self.db_operations_total.value}")

        # -- aaltohub_uptime_seconds --
        lines.append("# HELP aaltohub_uptime_seconds Seconds since the metrics registry was created.")
        lines.append("# TYPE aaltohub_uptime_seconds gauge")
        lines.append(f"aaltohub_uptime_seconds {time.time() - self._start_time:.1f}")

        # Prometheus text format requires a trailing newline
        lines.append("")
        return "\n".join(lines)


# Singleton instance -- import this from anywhere in the backend
metrics = MetricsRegistry()
