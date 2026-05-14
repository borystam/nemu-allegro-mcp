"""prepare_purchase produces handoff URLs without payment calls."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from allegro_mcp.tools import purchase_handoff


@pytest.mark.asyncio
async def test_prepare_purchase_returns_links(tool_context) -> None:
    mcp = FastMCP(name="t")
    purchase_handoff.register(mcp, tool_context)
    tool = await mcp.get_tool("prepare_purchase")
    result = await tool.fn(offer_id="123", quantity=2)
    assert result.web_url == "https://allegro.pl/oferta/123?quantity=2"
    assert result.app_deep_link == "allegro://offer/123?quantity=2"
    assert "public API does not expose payment endpoints" in result.note
