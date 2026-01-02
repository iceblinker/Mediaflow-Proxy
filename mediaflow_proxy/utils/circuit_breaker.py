import time
import logging
from enum import Enum
from typing import Dict, Any, Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class State(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class CircuitBreakerOpenException(Exception):
    def __init__(self, domain: str, failures: int):
        self.message = f"Circuit breaker OPEN for {domain} after {failures} failures"
        super().__init__(self.message)

class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: int = 30):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = State.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0

    def allow_request(self) -> bool:
        if self.state == State.CLOSED:
            return True
        
        if self.state == State.OPEN:
            elapsed = time.time() - self.last_failure_time
            if elapsed > self.recovery_timeout:
                self.state = State.HALF_OPEN
                logger.info(f"Circuit breaker '{self.name}' entering HALF_OPEN state (elapsed: {elapsed:.2f}s)")
                return True
            return False
            
        if self.state == State.HALF_OPEN:
            # In half-open, we typically allow 1 probe request.
            # For simplicity in this concurrent env, we admit requests.
            # Real implementation might need atomic locks, but Python GIL helps here.
            return True
            
        return False

    def record_success(self):
        if self.state != State.CLOSED:
            logger.info(f"Circuit breaker '{self.name}' recovered to CLOSED state")
            self.state = State.CLOSED
            self.failure_count = 0
        # If already CLOSED, just ensure count is 0
        self.failure_count = 0

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == State.CLOSED and self.failure_count >= self.failure_threshold:
            self.state = State.OPEN
            logger.warning(f"Circuit breaker '{self.name}' OPENED after {self.failure_count} failures")
        
        elif self.state == State.HALF_OPEN:
            self.state = State.OPEN
            logger.warning(f"Circuit breaker '{self.name}' re-OPENED during HALF_OPEN trial")

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Helper to wrap function calls"""
        if not self.allow_request():
            raise CircuitBreakerOpenException(self.name, self.failure_count)
        
        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

_breakers: Dict[str, CircuitBreaker] = {}

def get_circuit_breaker(domain: str, failure_threshold: int = 5, recovery_timeout: int = 30) -> CircuitBreaker:
    if domain not in _breakers:
        _breakers[domain] = CircuitBreaker(domain, failure_threshold, recovery_timeout)
    return _breakers[domain]

def get_domain_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.netloc or "unknown"
    except Exception:
        return "unknown"
