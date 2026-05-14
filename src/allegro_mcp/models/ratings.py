"""Ratings models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Rating(BaseModel):
    """A buyer's rating left for a seller after an order."""

    rating_id: str | None = None
    order_id: str
    seller_id: str | None = None
    seller_login: str | None = None
    rating: int
    comment: str | None = None
    submitted_at: datetime | None = None
