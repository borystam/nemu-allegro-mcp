"""Product catalogue models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Product(BaseModel):
    """A product from Allegro's master catalogue."""

    product_id: str
    name: str
    description: str | None = None
    category_id: str | None = None
    brand: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    ean: list[str] = Field(default_factory=list)
    parameters: list[dict[str, object]] = Field(default_factory=list)


class ProductSearchResult(BaseModel):
    """Result of `/sale/products`."""

    products: list[Product]
    total_count: int | None = None
    query_phrase: str | None = None
