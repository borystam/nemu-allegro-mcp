"""Coverage for list_bids, deep_search edge cases, suspicious medians."""

from __future__ import annotations

import re

import pytest
from fastmcp import FastMCP

from allegro_mcp.tools import bidding, deep_search, intel


@pytest.mark.asyncio
async def test_list_bids(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/users/me/bids",
        json={
            "bids": [
                {
                    "id": "B1",
                    "offer": {"id": "O1", "name": "x"},
                    "maxAmount": {"amount": "50", "currency": "PLN"},
                    "currentPrice": {"amount": "40", "currency": "PLN"},
                    "status": "winning",
                    "placedAt": "2024-01-01T00:00:00Z",
                    "auctionEndsAt": "2024-01-02T00:00:00Z",
                }
            ]
        },
    )
    mcp = FastMCP(name="t")
    bidding.register(mcp, tool_context)
    bids = await (await mcp.get_tool("list_bids")).fn()
    assert bids[0].bid_id == "B1"
    assert bids[0].status == bidding.BidStatus.WINNING


@pytest.mark.asyncio
async def test_deep_search_ean_branch_fires(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*offers/listing.*"),
        json={
            "items": {"regular": [{"id": "1", "sellingMode": {"price": {"amount": "1"}}}]},
            "totalCount": 1,
        },
        is_reusable=True,
    )
    mcp = FastMCP(name="t")
    deep_search.register(mcp, tool_context)
    result = await (await mcp.get_tool("deep_search")).fn(
        phrase="5901234123457",  # valid EAN-13
        budget_seconds=2.0,
    )
    names = {p.name for p in result.paths_taken}
    assert "ean_query" in names


@pytest.mark.asyncio
async def test_deep_search_with_hints(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*offers/listing.*"),
        json={"items": {"regular": []}, "totalCount": 0},
        is_reusable=True,
    )
    mcp = FastMCP(name="t")
    deep_search.register(mcp, tool_context)
    result = await (await mcp.get_tool("deep_search")).fn(
        phrase="iphone",
        hints={"category_id": "c1", "brand": "Apple", "mpn": "ABC", "ean": "5901234123457"},
        budget_seconds=2.0,
    )
    names = {p.name for p in result.paths_taken}
    assert {"phrase_in_category", "brand_query", "mpn_query", "ean_query"} <= names


@pytest.mark.asyncio
async def test_detect_suspicious_flags_outlier_price(
    allegro_client, tool_context, httpx_mock
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*sale/product-offers/OUT.*"),
        json={
            "id": "OUT",
            "name": "Phone",
            "sellingMode": {"price": {"amount": "1.00", "currency": "PLN"}},
            "seller": {"id": "S2", "login": "low"},
            "product": {"id": "PRX"},
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/users/S2",
        json={"id": "S2", "ratings": {"average": 4.5, "count": 200}},
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*offers/listing.*"),
        json={
            "items": {
                "regular": [
                    {"id": str(i), "sellingMode": {"price": {"amount": str(p)}}}
                    for i, p in enumerate([900.0, 920.0, 950.0, 970.0, 1000.0, 1100.0])
                ]
            }
        },
    )
    mcp = FastMCP(name="t")
    intel.register(mcp, tool_context)
    flags = await (await mcp.get_tool("detect_suspicious")).fn(offer_ids=["OUT"])
    assert any("σ below" in r for r in flags[0].reasons)
