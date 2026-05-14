"""Handoff to the Allegro web/app for the actual purchase.

The MCP never calls a payment endpoint — Allegro does not expose one in
its public REST API. We construct the deep link and the web URL and let
the human complete the transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from allegro_mcp.models.handoff import PurchaseHandoff

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.tools import ToolContext


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach purchase-handoff tools."""
    del context  # unused; the handoff is a pure URL construction

    @mcp.tool
    async def prepare_purchase(
        offer_id: Annotated[str, Field(description="Offer the user intends to buy")],
        quantity: Annotated[int, Field(ge=1, le=100)] = 1,
    ) -> PurchaseHandoff:
        """Return URLs the user can follow to complete the purchase.

        Use this once the user has chosen an offer. Allegro's public API
        does not expose a payment endpoint, so the agent cannot complete
        the purchase itself. The user finishes the flow in the Allegro
        web or mobile app via the URLs returned here.
        """
        web_url = f"https://allegro.pl/oferta/{offer_id}?quantity={quantity}"
        deep_link = f"allegro://offer/{offer_id}?quantity={quantity}"
        note = (
            "The Allegro public API does not expose payment endpoints. "
            "Follow the web URL or the deep link in the Allegro app to complete the purchase."
        )
        return PurchaseHandoff(
            offer_id=offer_id,
            quantity=quantity,
            web_url=web_url,
            app_deep_link=deep_link,
            note=note,
        )
