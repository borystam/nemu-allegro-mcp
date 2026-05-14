"""Seller models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SellerRatings(BaseModel):
    """Aggregated public seller ratings."""

    average_score: float | None = None
    review_count: int | None = None
    positive_pct: float | None = None
    super_seller: bool = False


class Seller(BaseModel):
    """Public seller profile."""

    seller_id: str
    login: str
    is_business: bool | None = None
    company_name: str | None = None
    location: str | None = None
    member_since: datetime | None = None
    ratings: SellerRatings | None = None
