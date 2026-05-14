"""Comparison models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from allegro_mcp.models.offer import Money


class ComparisonRow(BaseModel):
    """A row in a side-by-side comparison."""

    offer_id: str
    name: str
    price: Money
    delivery_cost: Money | None = None
    landed_cost: Money | None = None
    seller_login: str | None = None
    seller_score: float | None = None
    seller_review_count: int | None = None
    is_business: bool | None = None
    super_seller: bool = False
    free_delivery: bool | None = None
    handling_time: str | None = None
    condition: str | None = None
    smart: bool | None = None
    rank_score: float | None = None
    notes: list[str] = Field(default_factory=list)


class ComparisonTable(BaseModel):
    """Normalised comparison of multiple offers."""

    rows: list[ComparisonRow]
    weights: dict[str, float] | None = None
    best_offer_id: str | None = None
    reasoning: list[str] = Field(default_factory=list)
