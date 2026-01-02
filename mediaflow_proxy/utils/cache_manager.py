import logging
from typing import Any, Optional
from cachetools import TTLCache

logger = logging.getLogger(__name__)

class CacheManager:
    """
    A unified cache manager using TTLCache.
    """
    def __init__(self, maxsize: int = 1000, ttl: int = 600):
        """
        Initialize the cache manager.
        
        Args:
            maxsize (int): Maximum number of items in the cache. Defaults to 1000.
            ttl (int): Time to live in seconds. Defaults to 600 (10 minutes).
        """
        self._cache = TTLCache(maxsize=maxsize, ttl=ttl)

    def get(self, key: str) -> Optional[Any]:
        """Get an item from the cache."""
        value = self._cache.get(key)
        if value:
            logger.debug(f"Cache hit for key: {key}")
        return value

    def set(self, key: str, value: Any) -> None:
        """Set an item in the cache."""
        self._cache[key] = value
        logger.debug(f"Cache set for key: {key}")

    def invalidate(self, key: str) -> None:
        """Invalidate a specific key in the cache."""
        if key in self._cache:
            del self._cache[key]
            logger.info(f"Cache invalidated for key: {key}")

    def clear(self) -> None:
        """Clear the entire cache."""
        self._cache.clear()
        logger.info("Cache cleared")
