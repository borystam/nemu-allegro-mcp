"""Purchase / order history models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from allegro_mcp.models.offer import Money


class PurchaseLineItem(BaseModel):
    """A single offer purchased within an order."""

    offer_id: str
    name: str
    quantity: int
    unit_price: Money
    total_price: Money | None = None
    seller_id: str | None = None
    seller_login: str | None = None
    image_url: str | None = None


class Purchase(BaseModel):
    """A buyer-facing order record from `/order/checkout-forms/...` or equivalent."""

    order_id: str
    status: str
    created_at: datetime
    updated_at: datetime | None = None
    line_items: list[PurchaseLineItem] = Field(default_factory=list)
    total_price: Money | None = None
    delivery_address_summary: str | None = None
    delivery_method: str | None = None
    payment_status: str | None = None
    web_url: str | None = None
