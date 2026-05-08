import time


class TTLCache:
    """Simple in-memory cache with TTL support."""

    def __init__(self, ttl: int = 60):
        self._store: dict = {}
        self._ttl = ttl

    def get(self, key: str):
        """Return cached value if exists and not expired, else None."""
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.time() > entry["expires_at"]:
            del self._store[key]
            return None
        return entry["url"]

    def set(self, key: str, url: str) -> None:
        """Store a URL in the cache with TTL."""
        self._store[key] = {
            "url": url,
            "expires_at": time.time() + self._ttl,
        }

    def clear(self) -> None:
        """Clear all cache entries (useful for testing)."""
        self._store.clear()


# Module-level singleton used by the application
url_cache = TTLCache(ttl=60)
