"""Price-history persistence tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from allegro_mcp.persistence.price_history import PriceHistoryStore, PriceSnapshot


def _make_snap(
    offer_id: str, when: datetime, *, product_id: str | None = None, price: float = 100.0
) -> PriceSnapshot:
    return PriceSnapshot(
        offer_id=offer_id,
        product_id=product_id,
        price_amount=price,
        currency="PLN",
        captured_at=when,
    )


@pytest.mark.asyncio
async def test_record_and_read_by_offer(tmp_path: Path) -> None:
    store = PriceHistoryStore(tmp_path / "history.db")
    now = datetime.now(UTC)
    await store.record(_make_snap("o1", now, product_id="p1", price=100.0))
    await store.record(_make_snap("o1", now - timedelta(hours=1), product_id="p1", price=110.0))
    rows = await store.read("o1", now - timedelta(days=1))
    assert [r.price_amount for r in rows] == [110.0, 100.0]


@pytest.mark.asyncio
async def test_read_falls_back_to_product(tmp_path: Path) -> None:
    store = PriceHistoryStore(tmp_path / "history.db")
    now = datetime.now(UTC)
    await store.record(_make_snap("o1", now, product_id="p1"))
    rows = await store.read("p1", now - timedelta(days=1))
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_duplicate_primary_key_is_ignored(tmp_path: Path) -> None:
    store = PriceHistoryStore(tmp_path / "history.db")
    now = datetime.now(UTC)
    snap = _make_snap("o1", now, price=10.0)
    await store.record(snap)
    await store.record(snap)
    rows = await store.read("o1", now - timedelta(hours=1))
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_record_many_bulk(tmp_path: Path) -> None:
    store = PriceHistoryStore(tmp_path / "history.db")
    now = datetime.now(UTC)
    snaps = [
        _make_snap("o1", now, price=10.0),
        _make_snap("o2", now, price=20.0),
    ]
    count = await store.record_many(snaps)
    assert count == 2
