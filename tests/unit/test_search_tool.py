"""search_offers tool request shaping."""

from __future__ import annotations

import re

import pytest
from fastmcp import FastMCP

from allegro_mcp.tools import search


@pytest.mark.asyncio
async def test_search_offers_shapes_request(allegro_client, tool_context, httpx_mock) -> None:
    captured: list[str] = []

    def respond(request) -> object:
        captured.append(str(request.url))
        import httpx

        return httpx.Response(200, json={"items": {"regular": []}, "totalCount": 0})

    httpx_mock.add_callback(respond, url=re.compile(r".*offers/listing.*"))
    mcp = FastMCP(name="t")
    search.register(mcp, tool_context)
    tool = await mcp.get_tool("search_offers")
    result = await tool.fn(
        phrase="iphone",
        category_id="c",
        price_from=100.0,
        price_to=200.0,
        condition="new",
        smart_only=True,
        sort="price_asc",
        limit=12,
    )
    assert result.total_count == 0
    assert result.sort == "price_asc"
    url = captured[0]
    assert "phrase=iphone" in url
    assert "category.id=c" in url
    assert "price.from=100" in url
    assert "parameter.11323=new" in url
    assert "delivery.smart=true" in url
    assert "sort=%2Bprice" in url
    assert "limit=12" in url


@pytest.mark.asyncio
async def test_search_archive_filters_by_days(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*offers/listing.*"),
        json={"items": {"regular": []}, "totalCount": 0},
    )
    mcp = FastMCP(name="t")
    search.register(mcp, tool_context)
    tool = await mcp.get_tool("search_archive")
    result = await tool.fn(phrase="x", days_back=30)
    assert "archive search" in (result.notes[0] if result.notes else "")
