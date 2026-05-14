"""Offer-related models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Money(BaseModel):
    """A monetary amount with currency code."""

    model_config = ConfigDict(frozen=True)

    amount: float
    currency: str = "PLN"

    @classmethod
    def from_api(cls, raw: Any) -> Money | None:
        if raw is None:
            return None
        if isinstance(raw, Money):
            return raw
        if isinstance(raw, dict):
            amount = raw.get("amount") or raw.get("value")
            currency = raw.get("currency") or "PLN"
            if amount is None:
                return None
            return cls(amount=float(amount), currency=str(currency))
        return None


class OfferSummary(BaseModel):
    """Compact offer record used in listings."""

    offer_id: str
    name: str
    price: Money
    seller_id: str | None = None
    seller_login: str | None = None
    condition: str | None = None
    quantity_available: int | None = None
    is_business: bool | None = None
    free_delivery: bool | None = None
    smart: bool | None = None
    image_url: str | None = None
    web_url: str | None = None
    product_id: str | None = None
    category_id: str | None = None


class OfferDelivery(BaseModel):
    """Delivery options summary."""

    free_delivery: bool | None = None
    handling_time: str | None = None
    shipping_rates_id: str | None = None
    options: list[dict[str, Any]] = Field(default_factory=list)


class Offer(BaseModel):
    """Full offer detail returned from `/sale/product-offers/{id}` or similar."""

    offer_id: str
    name: str
    description_html: str | None = None
    price: Money
    original_price: Money | None = None
    seller_id: str | None = None
    seller_login: str | None = None
    is_business: bool | None = None
    condition: str | None = None
    quantity_available: int | None = None
    stock_unit: str | None = None
    category_id: str | None = None
    category_path: list[str] = Field(default_factory=list)
    product_id: str | None = None
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    promotion_flags: list[str] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    web_url: str | None = None
    publication_started_at: datetime | None = None
    publication_ending_at: datetime | None = None
    delivery: OfferDelivery | None = None
    rating: float | None = None
    rating_count: int | None = None
