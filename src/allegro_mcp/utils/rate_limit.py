"""Async token-bucket rate limiter."""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """Simple token bucket. Acquire `n` tokens; await refill if empty.

    Allegro uses a per-user leaky bucket; we shape our client below that limit
    to avoid 429s under bursty workloads such as `deep_search`.
    """

    def __init__(self, *, rate: float, capacity: int) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._rate = rate
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def capacity(self) -> int:
        return int(self._capacity)

    @property
    def rate(self) -> float:
        return self._rate

    async def acquire(self, n: int = 1) -> None:
        """Block until `n` tokens are available, then consume them."""
        if n <= 0:
            return
        if n > self._capacity:
            raise ValueError(f"requested {n} tokens but bucket capacity is {int(self._capacity)}")
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= n:
                    self._tokens -= n
                    return
                deficit = n - self._tokens
                wait = deficit / self._rate
            await asyncio.sleep(wait)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed <= 0:
            return
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last = now

    def tokens_available(self) -> float:
        """Snapshot of current token count; primarily useful in tests."""
        self._refill()
        return self._tokens
