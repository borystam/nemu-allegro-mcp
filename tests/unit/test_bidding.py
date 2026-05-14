"""bidding tool guards binding actions."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from allegro_mcp.tools import bidding


@pytest.mark.asyncio
async def test_place_bid_refuses_without_confirm(tool_context) -> None:
    mcp = FastMCP(name="t")
    bidding.register(mcp, tool_context)
    tool = await mcp.get_tool("place_bid")
    with pytest.raises(bidding.ConfirmationRequired):
        await tool.fn(offer_id="123", amount=10.0, confirm=False)


@pytest.mark.asyncio
async def test_place_bid_with_confirm_puts(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        method="PUT",
        url="https://api.allegro.pl.allegrosandbox.pl/bidding/offers/123/bid",
        json={"offer": {"id": "123", "name": "n"}, "status": "winning"},
    )
    mcp = FastMCP(name="t")
    bidding.register(mcp, tool_context)
    tool = await mcp.get_tool("place_bid")
    bid = await tool.fn(offer_id="123", amount=10.0, confirm=True)
    assert bid.offer_id == "123"
    assert bid.status == bidding.BidStatus.WINNING
