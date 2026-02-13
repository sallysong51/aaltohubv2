"""
Bounded Cache with TTL and LRU Eviction

Prevents unbounded memory growth in long-running services by enforcing:
1. Maximum size limit (LRU eviction when full)
2. Time-to-live expiration (TTL per entry)

Thread-safe for asyncio single-threaded event loop (not thread-safe for
multi-threaded access).
"""
import time
from collections import OrderedDict
from typing import TypeVar, Generic, Optional

T = TypeVar('T')


class BoundedCache(Generic[T]):
    """Size-limited TTL cache with LRU eviction.

    Example:
        cache = BoundedCache[bool](max_size=1000, ttl=60.0)
        cache.set("key1", True)
        value = cache.get("key1")  # Returns True
        # After 60s or when cache exceeds 1000 entries:
        value = cache.get("key1")  # Returns None
    """

    def __init__(self, max_size: int = 5000, ttl: float = 300.0):
        """Initialize bounded cache.

        Args:
            max_size: Maximum number of entries before LRU eviction
            ttl: Time-to-live in seconds for each entry
        """
        self._cache: OrderedDict[str, tuple[T, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl

    def get(self, key: str) -> Optional[T]:
        """Get value from cache if not expired.

        Args:
            key: Cache key

        Returns:
            Cached value if found and not expired, None otherwise
        """
        if key not in self._cache:
            return None

        value, expire_at = self._cache[key]
        now = time.monotonic()

        if now >= expire_at:
            # Expired — remove from cache
            del self._cache[key]
            return None

        # Move to end (mark as recently used for LRU)
        self._cache.move_to_end(key)
        return value

    def set(self, key: str, value: T) -> None:
        """Set value in cache with TTL.

        Args:
            key: Cache key
            value: Value to cache
        """
        now = time.monotonic()
        expire_at = now + self._ttl

        # Remove if already exists (will re-add at end)
        if key in self._cache:
            del self._cache[key]

        # Evict LRU entry if cache is full
        if len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)  # Remove oldest (first) item

        self._cache[key] = (value, expire_at)

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()

    def cleanup_expired(self) -> int:
        """Remove expired entries from cache.

        Returns:
            Number of entries removed
        """
        now = time.monotonic()
        expired_keys = [
            key for key, (_, expire_at) in self._cache.items()
            if now >= expire_at
        ]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)

    def __len__(self) -> int:
        """Return current cache size."""
        return len(self._cache)

    def __contains__(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        return self.get(key) is not None
