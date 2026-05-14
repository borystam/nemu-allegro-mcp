"""Bidding models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from allegro_mcp.models.offer import Money


class BidStatus(StrEnum):
    """Status of a bid as reported by Allegro."""

    WINNING = "winning"
    OUTBID = "outbid"
    WON = "won"
    LOST = "lost"
    ENDED = "ended"
    UNKNOWN = "unknown"


class Bid(BaseModel):
    """A single bid on an auction offer."""

    bid_id: str | None = None
    offer_id: str
    offer_name: str | None = None
    maximum_bid: Money | None = None
    current_price: Money | None = None
    status: BidStatus = BidStatus.UNKNOWN
    placed_at: datetime | None = None
    auction_ends_at: datetime | None = None
