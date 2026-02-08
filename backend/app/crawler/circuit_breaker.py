"""Circuit breaker for DB operations with escalating backoff.

States: closed (normal) -> open (paused) -> half-open (testing).
Opens after CB_FAILURE_THRESHOLD failures within CB_FAILURE_WINDOW seconds.
"""
import logging
import time

logger = logging.getLogger(__name__)

CB_FAILURE_THRESHOLD = 5  # failures before opening
CB_FAILURE_WINDOW = 60  # seconds
CB_RECOVERY_TIMEOUT = 30  # seconds to wait before retrying


class CircuitBreaker:
    """Circuit breaker with escalating backoff.

    Escalation: each consecutive open cycle doubles the recovery timeout
    (30s -> 60s -> 120s -> 300s cap). Resets on successful write.
    Alerts via Sentry after 3 consecutive open cycles.

    Thread safety: NOT thread-safe. Only accessed from async coroutines
    on the main event loop.
    """

    _CB_MAX_RECOVERY = 300  # 5 minutes cap

    def __init__(self) -> None:
        self._failures: list[float] = []
        self._state = "closed"  # closed | open | half-open
        self._opened_at: float = 0
        self._consecutive_opens: int = 0

    @property
    def _current_recovery_timeout(self) -> float:
        return min(CB_RECOVERY_TIMEOUT * (2 ** self._consecutive_opens), self._CB_MAX_RECOVERY)

    @property
    def is_open(self) -> bool:
        if self._state == "closed":
            return False
        if self._state == "open":
            if time.monotonic() - self._opened_at >= self._current_recovery_timeout:
                self._state = "half-open"
                return False
            return True
        return False  # half-open allows one attempt

    def record_success(self) -> None:
        self._state = "closed"
        self._failures.clear()
        self._consecutive_opens = 0

    def record_failure(self) -> None:
        now = time.monotonic()
        self._failures = [t for t in self._failures if now - t < CB_FAILURE_WINDOW]
        self._failures.append(now)
        if len(self._failures) >= CB_FAILURE_THRESHOLD:
            self._state = "open"
            self._opened_at = now
            self._consecutive_opens += 1
            recovery = min(CB_RECOVERY_TIMEOUT * (2 ** (self._consecutive_opens - 1)), self._CB_MAX_RECOVERY)
            logger.warning(
                "Circuit breaker OPEN (cycle #%d) -- next test in %ds",
                self._consecutive_opens, recovery,
            )
            if self._consecutive_opens >= 3:
                try:
                    import sentry_sdk
                    if sentry_sdk.is_initialized():
                        sentry_sdk.capture_message(
                            f"Circuit breaker stuck open ({self._consecutive_opens} cycles, "
                            f"next retry in {recovery}s)",
                            level="error",
                        )
                except Exception:
                    pass
