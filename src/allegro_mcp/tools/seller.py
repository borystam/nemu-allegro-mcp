"""Seller profile and listings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from allegro_mcp.models.offer import OfferSummary
from allegro_mcp.models.seller import Seller
from allegro_mcp.tools._parsers import parse_offer_summary, parse_seller

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.tools import ToolContext


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach seller-discovery tools."""

    @mcp.tool
    async def get_seller(
        seller_id: Annotated[str, Field(description="Allegro seller (user) identifier")],
    ) -> Seller:
        """Fetch a public seller profile.

        Use this to inspect a seller's name, location, business status, and
        aggregated rating signals before purchasing. For a composite trust
        score with reasoning, prefer `seller_trust_signal`.
        """
        payload = await context.client.get(f"/users/{seller_id}")
        return parse_seller(payload)

    @mcp.tool
    async def list_seller_offers(
        seller_id: Annotated[str, Field(description="Allegro seller identifier")],
        phrase: Annotated[
            str | None,
            Field(description="Optional phrase to filter the seller's catalogue"),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=60)] = 24,
    ) -> list[OfferSummary]:
        """List active offers from a specific seller.

        Use this when you want everything a seller currently lists, or to
        find alternatives within the same seller's shop. Do not use it for
        cross-seller comparison — `compare_offers` is the right tool there.
        """
        params = {
            "seller.id": seller_id,
            "phrase": phrase,
            "limit": limit,
        }
        payload = await context.client.get("/offers/listing", params=params)
        items = (payload.get("items") or {}).get("regular") or []
        return [parse_offer_summary(item) for item in items]
