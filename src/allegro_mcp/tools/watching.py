"""Watched-offers management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from allegro_mcp.models.offer import OfferSummary
from allegro_mcp.models.watching import WatchResult
from allegro_mcp.tools._parsers import parse_offer_summary

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.tools import ToolContext


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach watching tools."""

    @mcp.tool
    async def list_watched() -> list[OfferSummary]:
        """List offers the authenticated account is currently watching.

        Use this to surface what the user has shortlisted, or to feed
        `price_history` and `detect_suspicious` over their existing watch
        list. Do not use this for general search.
        """
        payload = await context.client.get("/watchlist")
        items = payload.get("watchedOffers") or payload.get("offers") or []
        return [parse_offer_summary(item) for item in items]

    @mcp.tool
    async def watch_offer(
        offer_id: Annotated[str, Field(description="Offer to start watching")],
    ) -> WatchResult:
        """Add an offer to the authenticated account's watch list.

        Use this when the user explicitly asks to follow an offer. Watching
        is also a prerequisite for the local price-history scheduler to
        record snapshots.
        """
        await context.client.post(
            "/watchlist",
            json={"offer": {"id": offer_id}},
        )
        return WatchResult(offer_id=offer_id, watched=True)

    @mcp.tool
    async def unwatch_offer(
        offer_id: Annotated[str, Field(description="Offer to stop watching")],
    ) -> WatchResult:
        """Remove an offer from the watch list.

        Use this when the user has decided against an offer or has already
        purchased the item elsewhere.
        """
        await context.client.delete(f"/watchlist/{offer_id}")
        return WatchResult(offer_id=offer_id, watched=False)
