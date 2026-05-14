"""Models for the synthesised `deep_search` tool."""

from __future__ import annotations

from pydantic import BaseModel, Field

from allegro_mcp.models.offer import OfferSummary


class SearchPath(BaseModel):
    """Record of a single search branch executed by `deep_search`."""

    name: str
    query: dict[str, object] = Field(default_factory=dict)
    result_count: int = 0
    elapsed_ms: int = 0
    error: str | None = None


class DeepSearchResult(BaseModel):
    """Merged, deduplicated, ranked output of a deep multi-branch search."""

    phrase: str
    offers: list[OfferSummary]
    paths_taken: list[SearchPath]
    total_unique_offers: int
    total_unique_products: int
    truncated: bool = False
