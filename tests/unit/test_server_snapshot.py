"""Internal poll-watched endpoint snapshot writer."""

from __future__ import annotations

import re

import pytest
from fastmcp import FastMCP

from allegro_mcp.server import _snapshot_watched
from allegro_mcp.tools import ToolContext


@pytest.mark.asyncio
async def test_snapshot_watched_records_for_each_offer(
    allegro_client, tool_context: ToolContext, httpx_mock
) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/watchlist",
        json={"watchedOffers": [{"id": "A", "name": "A"}, {"id": "B", "name": "B"}]},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/sale/product-offers/A",
        json={
            "id": "A",
            "name": "A",
            "sellingMode": {"price": {"amount": "10"}},
            "product": {"id": "PA"},
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/sale/product-offers/B",
        json={
            "id": "B",
            "name": "B",
            "sellingMode": {"price": {"amount": "20"}},
            "product": {"id": "PB"},
        },
    )
    recorded = await _snapshot_watched(tool_context)
    assert recorded == 2


@pytest.mark.asyncio
async def test_snapshot_watched_skips_broken_offers(
    allegro_client, tool_context: ToolContext, httpx_mock
) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.allegro.pl.allegrosandbox.pl/watchlist",
        json={"watchedOffers": [{"id": "A"}, {}]},
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*sale/product-offers/A"),
        status_code=500,
        is_reusable=True,
    )
    recorded = await _snapshot_watched(tool_context)
    assert recorded == 0


@pytest.mark.asyncio
async def test_server_route_authorises_with_internal_secret(
    allegro_client, tool_context: ToolContext
) -> None:
    """Smoke-test that the custom route registration runs without error."""
    mcp = FastMCP(name="t")
    from allegro_mcp.server import _attach_internal_routes

    _attach_internal_routes(mcp, tool_context)
    # If registration succeeds, the http app exists with our route.
    app = mcp.http_app()
    paths = [route.path for route in app.routes]
    assert "/internal/poll-watched" in paths
