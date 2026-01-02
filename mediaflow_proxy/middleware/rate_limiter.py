import time
import os
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.requests import Request
from cachetools import TTLCache

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit: int = 100, window: int = 60):
        super().__init__(app)
        self.limit = limit
        self.window = window
        self.redis_url = os.getenv("REDIS_URL")
        self.redis = None
        
        if HAS_REDIS and self.redis_url:
            # Initialize Redis client
            try:
                self.redis = redis.from_url(self.redis_url, encoding="utf-8", decode_responses=True)
                logger.info(f"Rate Limiter: Active (Redis backed at {self.redis_url})")
            except Exception as e:
                logger.error(f"Rate Limiter: Failed to connect to Redis: {e}")
                self.redis = None

        if not self.redis:
            # Cache stores [start_time, count] for each IP
            # TTL ensures cleaner memory management for inactive IPs
            self.cache = TTLCache(maxsize=10000, ttl=window * 2)
            logger.info("Rate Limiter: Active (In-Memory)")

    async def dispatch(self, request: Request, call_next):
        # Exclude health check from rate limiting
        if request.url.path == "/health" or request.url.path == "/favicon.ico":
             return await call_next(request)

        # Get client IP (support locally trusted proxies like Caddy)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # X-Forwarded-For: client, proxy1, proxy2
            # We take the first IP as the real client
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"

        if self.redis:
            key = f"rate_limit:{ip}"
            try:
                # Lua script for atomic increment-and-expire
                # Returns the current count
                # If count == 1 (key created), set expiry
                script = """
                local current = redis.call("INCR", KEYS[1])
                if tonumber(current) == 1 then
                    redis.call("EXPIRE", KEYS[1], ARGV[1])
                end
                return current
                """
                count = await self.redis.eval(script, 1, key, self.window)
                
                if count > self.limit:
                    return JSONResponse(
                        status_code=429, 
                        content={"detail": "Too Many Requests", "retry_after": self.window}
                    )
            except Exception as e:
                logger.error(f"Rate Limiter: Redis error: {e}")
                # Fail open (allow request) or fallback to memory? 
                # Fail open is safer for availability.
                pass
        else:
            # In-memory logic
            now = time.time()
            entry = self.cache.get(ip)
            if not entry:
                # New entry: [start_time, current_count]
                entry = [now, 1]
                self.cache[ip] = entry
            else:
                start_time, count = entry
                if now - start_time > self.window:
                    # Window passed, reset counter
                    entry = [now, 1]
                    self.cache[ip] = entry
                else:
                    # In window
                    if count >= self.limit:
                        return JSONResponse(
                            status_code=429, 
                            content={"detail": "Too Many Requests", "retry_after": int(self.window - (now - start_time))}
                        )
                    entry[1] += 1
                    self.cache[ip] = entry
                
        return await call_next(request)
