"""Local price-history store backed by SQLite."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

import aiosqlite


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    """A single price observation."""

    offer_id: str
    product_id: str | None
    price_amount: float
    currency: str
    captured_at: datetime
    seller_id: str | None = None
    stock_available: int | None = None


def _load_schema() -> str:
    return (
        resources.files("allegro_mcp.persistence")
        .joinpath("schema.sql")
        .read_text(encoding="utf-8")
    )


class PriceHistoryStore:
    """Thin async wrapper around the price-history schema."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    @property
    def db_path(self) -> Path:
        return self._db_path

    async def initialise(self) -> None:
        """Create the database file and apply schema if needed."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_load_schema())
            await db.commit()

    async def record(self, snapshot: PriceSnapshot) -> None:
        """Insert a snapshot. Ignores duplicate `(offer_id, captured_at)` rows."""
        await self.initialise()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO price_snapshots
                    (offer_id, product_id, price_amount, currency,
                     captured_at, seller_id, stock_available)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.offer_id,
                    snapshot.product_id,
                    snapshot.price_amount,
                    snapshot.currency,
                    snapshot.captured_at.astimezone(UTC).isoformat(),
                    snapshot.seller_id,
                    snapshot.stock_available,
                ),
            )
            await db.commit()

    async def record_many(self, snapshots: list[PriceSnapshot]) -> int:
        """Bulk insert; returns the number of rows attempted."""
        if not snapshots:
            return 0
        await self.initialise()
        rows = [
            (
                s.offer_id,
                s.product_id,
                s.price_amount,
                s.currency,
                s.captured_at.astimezone(UTC).isoformat(),
                s.seller_id,
                s.stock_available,
            )
            for s in snapshots
        ]
        async with aiosqlite.connect(self._db_path) as db:
            await db.executemany(
                """
                INSERT OR IGNORE INTO price_snapshots
                    (offer_id, product_id, price_amount, currency,
                     captured_at, seller_id, stock_available)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            await db.commit()
        return len(rows)

    async def read(self, offer_or_product_id: str, since: datetime) -> list[PriceSnapshot]:
        """Read snapshots for an offer ID; falls back to product ID."""
        await self.initialise()
        since_iso = since.astimezone(UTC).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await self._fetch_by_offer(db, offer_or_product_id, since_iso)
            if rows:
                return rows
            return await self._fetch_by_product(db, offer_or_product_id, since_iso)

    @staticmethod
    async def _fetch_by_offer(
        db: aiosqlite.Connection, identifier: str, since_iso: str
    ) -> list[PriceSnapshot]:
        async with db.execute(
            """
            SELECT offer_id, product_id, price_amount, currency,
                   captured_at, seller_id, stock_available
            FROM price_snapshots
            WHERE offer_id = ? AND captured_at >= ?
            ORDER BY captured_at ASC
            """,
            (identifier, since_iso),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_snapshot(row) for row in rows]

    @staticmethod
    async def _fetch_by_product(
        db: aiosqlite.Connection, identifier: str, since_iso: str
    ) -> list[PriceSnapshot]:
        async with db.execute(
            """
            SELECT offer_id, product_id, price_amount, currency,
                   captured_at, seller_id, stock_available
            FROM price_snapshots
            WHERE product_id = ? AND captured_at >= ?
            ORDER BY captured_at ASC
            """,
            (identifier, since_iso),
        ) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_snapshot(row) for row in rows]


def _row_to_snapshot(row: aiosqlite.Row) -> PriceSnapshot:
    captured = row["captured_at"]
    captured_at = datetime.fromisoformat(captured) if isinstance(captured, str) else captured
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=UTC)
    return PriceSnapshot(
        offer_id=row["offer_id"],
        product_id=row["product_id"],
        price_amount=float(row["price_amount"]),
        currency=row["currency"],
        captured_at=captured_at,
        seller_id=row["seller_id"],
        stock_available=row["stock_available"],
    )
