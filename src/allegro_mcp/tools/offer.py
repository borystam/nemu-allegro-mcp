"""Offer detail."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from allegro_mcp.models.offer import Offer
from allegro_mcp.tools._parsers import parse_offer

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.tools import ToolContext


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach offer-detail tools."""

    @mcp.tool
    async def get_offer(
        offer_id: Annotated[str, Field(description="Allegro offer identifier (numeric string)")],
    ) -> Offer:
        """Fetch full detail for a single offer.

        Use this once you have narrowed down to a candidate offer from
        search results and want the complete description, parameters,
        seller info, and delivery options before deciding. Do not use this
        in bulk over many offers; prefer `compare_offers` for that.
        """
        payload = await context.client.get(f"/sale/product-offers/{offer_id}")
        return parse_offer(payload)
