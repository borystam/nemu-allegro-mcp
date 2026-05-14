"""Search models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from allegro_mcp.models.offer import OfferSummary


class SearchFilter(BaseModel):
    """Filter facet returned by Allegro's listing endpoint."""

    id: str
    name: str
    values: list[dict[str, str]] = Field(default_factory=list)


class SearchResult(BaseModel):
    """List of offers plus pagination and filter metadata."""

    total_count: int
    offers: list[OfferSummary]
    promoted_offers: list[OfferSummary] = Field(default_factory=list)
    filters: list[SearchFilter] = Field(default_factory=list)
    offset: int = 0
    limit: int = 0
    sort: str | None = None
    notes: list[str] = Field(default_factory=list)
