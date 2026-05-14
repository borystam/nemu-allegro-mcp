"""Rate-limiter behaviour."""

from __future__ import annotations

import asyncio
import time

import pytest

from allegro_mcp.utils.rate_limit import TokenBucket


@pytest.mark.asyncio
async def test_immediate_acquire_within_capacity() -> None:
    bucket = TokenBucket(rate=100.0, capacity=5)
    start = time.monotonic()
    for _ in range(5):
        await bucket.acquire()
    assert time.monotonic() - start < 0.05


@pytest.mark.asyncio
async def test_burst_then_throttle() -> None:
    bucket = TokenBucket(rate=20.0, capacity=2)
    await bucket.acquire()
    await bucket.acquire()
    start = time.monotonic()
    await bucket.acquire()
    elapsed = time.monotonic() - start
    # 1 token / 20 per second = 50ms. Allow scheduler slack.
    assert 0.03 < elapsed < 0.3


def test_capacity_validation() -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate=10.0, capacity=0)
    with pytest.raises(ValueError):
        TokenBucket(rate=0.0, capacity=5)


@pytest.mark.asyncio
async def test_acquire_more_than_capacity_raises() -> None:
    bucket = TokenBucket(rate=10.0, capacity=2)
    with pytest.raises(ValueError):
        await bucket.acquire(5)


@pytest.mark.asyncio
async def test_zero_acquire_is_noop() -> None:
    bucket = TokenBucket(rate=10.0, capacity=2)
    await bucket.acquire(0)
    assert bucket.tokens_available() == pytest.approx(2.0, rel=0.01)


@pytest.mark.asyncio
async def test_parallel_acquires_serialise() -> None:
    bucket = TokenBucket(rate=50.0, capacity=3)

    async def acquire_one() -> None:
        await bucket.acquire()

    await asyncio.gather(*(acquire_one() for _ in range(3)))
    assert bucket.tokens_available() < 1
