"""Intel models: trust signals, suspicion flags, landed cost, price history."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from allegro_mcp.models.offer import Money


class SuspicionFlag(BaseModel):
    """A flag indicating a potentially-suspicious offer."""

    offer_id: str
    severity: str
    reasons: list[str] = Field(default_factory=list)
    signals: dict[str, object] = Field(default_factory=dict)


class TrustSignal(BaseModel):
    """Composite seller-trust assessment."""

    seller_id: str
    score: float
    band: str
    components: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class PricePoint(BaseModel):
    """A single historical price observation."""

    captured_at: datetime
    price: Money
    stock_available: int | None = None


class PriceHistory(BaseModel):
    """A windowed price-history summary for an offer or product."""

    offer_id: str | None = None
    product_id: str | None = None
    window_days: int
    points: list[PricePoint] = Field(default_factory=list)
    current_price: Money | None = None
    median_price: Money | None = None
    lowest_ever_price: Money | None = None
    highest_ever_price: Money | None = None
    delta_vs_lowest_pct: float | None = None
    dip_detected: bool = False
    notes: list[str] = Field(default_factory=list)


class LandedCost(BaseModel):
    """Total cost of an offer delivered to a given postcode."""

    offer_id: str
    base_price: Money
    quantity: int
    delivery_method: str | None = None
    delivery_cost: Money | None = None
    total: Money
    postal_code: str | None = None
    estimated_arrival: str | None = None
    notes: list[str] = Field(default_factory=list)
