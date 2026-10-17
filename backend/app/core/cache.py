"""Multi-tier caching layer per TECH_REQUIREMENTS.md §2 and PRD.md §5."""

import hashlib
import logging
import time
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class CacheEntry:
    """Represents a cached item with an expiration timestamp."""

    def __init__(self, value: Any, ttl_seconds: int) -> None:
        self.value = value
        self.expires_at = time.time() + ttl_seconds


class MultiTierCache:
    """In-memory LRU and TTL-based cache with workspace invalidation support."""

    def __init__(
        self,
        max_entries: int = settings.CACHE_MAX_ENTRIES,
        default_ttl: int = settings.CACHE_TTL_SECONDS,
    ) -> None:
        self.max_entries = max_entries
        self.default_ttl = default_ttl
        self._store: dict[str, CacheEntry] = {}
        self._workspace_keys: dict[str, set[str]] = {}
        self.hits: int = 0
        self.misses: int = 0

    def _make_key(self, prefix: str, raw_key: str) -> str:
        h = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]
        return f"{prefix}:{h}"

    def get(self, key: str) -> Any:
        """Retrieves an item from cache if not expired. Returns None on miss/expiry."""
        if not settings.ENABLE_CACHE:
            return None

        entry = self._store.get(key)
        if not entry:
            self.misses += 1
            return None

        if time.time() > entry.expires_at:
            # Expired
            self._store.pop(key, None)
            self.misses += 1
            return None

        self.hits += 1
        return entry.value

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
        workspace_id: str | None = None,
    ) -> None:
        """Stores an item with TTL and optional workspace association for invalidation."""
        if not settings.ENABLE_CACHE:
            return

        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl

        # Evict oldest entry if capacity reached
        if len(self._store) >= self.max_entries:
            oldest_key = next(iter(self._store))
            self._store.pop(oldest_key, None)

        self._store[key] = CacheEntry(value=value, ttl_seconds=ttl)

        if workspace_id:
            if workspace_id not in self._workspace_keys:
                self._workspace_keys[workspace_id] = set()
            self._workspace_keys[workspace_id].add(key)

    def delete(self, key: str) -> None:
        """Deletes a single key."""
        self._store.pop(key, None)

    def invalidate_workspace(self, workspace_id: str) -> int:
        """Invalidates all cached queries, retrieval, and summaries for a workspace."""
        keys = self._workspace_keys.pop(workspace_id, set())
        for k in keys:
            self._store.pop(k, None)
        logger.info("Invalidated %d cache entries for workspace '%s'", len(keys), workspace_id)
        return len(keys)

    def clear(self) -> None:
        """Flushes all cached entries."""
        self._store.clear()
        self._workspace_keys.clear()
        self.hits = 0
        self.misses = 0

    @property
    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        rate = round((self.hits / total * 100.0), 1) if total > 0 else 0.0
        return {
            "entries_count": len(self._store),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate_pct": rate,
        }


# Global application cache singleton
app_cache = MultiTierCache()
