"""Internal snapshot-offers endpoint."""

from __future__ import annotations

import re

import pytest
from fastmcp import FastMCP

from allegro_mcp.server import _snapshot_offers
from allegro_mcp.tools import ToolContext


@pytest.mark.asyncio
async def test_snapshot_offers_records_for_each_offer(
    allegro_client, tool_context: ToolContext, httpx_mock
) -> None:
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
    recorded = await _snapshot_offers(tool_context, ["A", "B"])
    assert recorded == 2


@pytest.mark.asyncio
async def test_snapshot_offers_skips_broken_offers(
    allegro_client, tool_context: ToolContext, httpx_mock
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*sale/product-offers/A"),
        status_code=500,
        is_reusable=True,
    )
    recorded = await _snapshot_offers(tool_context, ["A"])
    assert recorded == 0


@pytest.mark.asyncio
async def test_internal_snapshot_route_is_attached(
    allegro_client, tool_context: ToolContext
) -> None:
    """The /internal/snapshot-offers route should be registered."""
    mcp = FastMCP(name="t")
    from allegro_mcp.server import _attach_internal_routes

    _attach_internal_routes(mcp, tool_context)
    app = mcp.http_app()
    paths = [route.path for route in app.routes]
    assert "/internal/snapshot-offers" in paths
    # Regression: ensure the dead /internal/poll-watched route is not re-added.
    assert "/internal/poll-watched" not in paths


def test_coerce_offer_ids_normalises_input() -> None:
    from allegro_mcp.server import _coerce_offer_ids

    assert _coerce_offer_ids({"offer_ids": ["1", "  2 ", 3]}) == ["1", "2", "3"]
    assert _coerce_offer_ids({"offer_ids": []}) == []
    assert _coerce_offer_ids({"offer_ids": ["", "  "]}) == []
    assert _coerce_offer_ids({"offer_ids": "1"}) is None
    assert _coerce_offer_ids("not a dict") is None
    assert _coerce_offer_ids(None) is None
