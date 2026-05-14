"""Intel: suspicion, trust, price history."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastmcp import FastMCP

from allegro_mcp.persistence.price_history import PriceSnapshot
from allegro_mcp.tools import intel


@pytest.mark.asyncio
async def test_seller_trust_signal_bands_high(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.allegro.pl.allegrosandbox.pl/users/1",
        json={
            "id": "1",
            "login": "best",
            "kind": "BUSINESS",
            "company": {"name": "Co"},
            "ratings": {"average": 4.95, "count": 1500, "positivePercentage": 99.8},
            "superSeller": True,
        },
    )
    mcp = FastMCP(name="t")
    intel.register(mcp, tool_context)
    tool = await mcp.get_tool("seller_trust_signal")
    signal = await tool.fn(seller_id="1")
    assert signal.band == "high"
    assert signal.components["super_seller"] == 1.0


@pytest.mark.asyncio
async def test_seller_trust_signal_notes_low_volume(
    allegro_client, tool_context, httpx_mock
) -> None:
    httpx_mock.add_response(
        url="https://api.allegro.pl.allegrosandbox.pl/users/2",
        json={
            "id": "2",
            "login": "new",
            "ratings": {"average": 5.0, "count": 5, "positivePercentage": 100.0},
        },
    )
    mcp = FastMCP(name="t")
    intel.register(mcp, tool_context)
    tool = await mcp.get_tool("seller_trust_signal")
    signal = await tool.fn(seller_id="2")
    assert any("fewer than 50" in n for n in signal.notes)


@pytest.mark.asyncio
async def test_price_history_returns_empty_for_unknown(tool_context) -> None:
    mcp = FastMCP(name="t")
    intel.register(mcp, tool_context)
    tool = await mcp.get_tool("price_history")
    result = await tool.fn(offer_id_or_product_id="missing", days=30)
    assert result.points == []
    assert any("no history" in n for n in result.notes)


@pytest.mark.asyncio
async def test_price_history_detects_dip(tool_context) -> None:
    now = datetime.now(UTC)
    snaps = [
        PriceSnapshot(
            offer_id="o",
            product_id="p",
            price_amount=100.0,
            currency="PLN",
            captured_at=now - timedelta(days=10),
        ),
        PriceSnapshot(
            offer_id="o",
            product_id="p",
            price_amount=100.0,
            currency="PLN",
            captured_at=now - timedelta(days=5),
        ),
        PriceSnapshot(
            offer_id="o", product_id="p", price_amount=70.0, currency="PLN", captured_at=now
        ),
    ]
    await tool_context.history.record_many(snaps)
    mcp = FastMCP(name="t")
    intel.register(mcp, tool_context)
    tool = await mcp.get_tool("price_history")
    result = await tool.fn(offer_id_or_product_id="o", days=30)
    assert result.dip_detected is True
    assert result.lowest_ever_price is not None
    assert result.lowest_ever_price.amount == 70.0


@pytest.mark.asyncio
async def test_detect_suspicious_flags_low_review_count(
    allegro_client, tool_context, httpx_mock
) -> None:
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*sale/product-offers/.*"),
        json={
            "id": "OF1",
            "name": "Phone",
            "sellingMode": {"price": {"amount": "1000.00", "currency": "PLN"}},
            "seller": {"id": "S1", "login": "sneak"},
            "stock": {"available": 1},
            "product": {"id": "PR1"},
        },
        is_reusable=True,
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*users/S1"),
        json={"id": "S1", "login": "sneak", "ratings": {"average": 4.0, "count": 3}},
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r".*offers/listing.*"),
        json={
            "items": {
                "regular": [
                    {"id": "x", "sellingMode": {"price": {"amount": "1100"}}},
                    {"id": "y", "sellingMode": {"price": {"amount": "1200"}}},
                ]
            }
        },
    )
    mcp = FastMCP(name="t")
    intel.register(mcp, tool_context)
    tool = await mcp.get_tool("detect_suspicious")
    flags = await tool.fn(offer_ids=["OF1"])
    assert flags
    assert any("3 reviews" in r for r in flags[0].reasons)
