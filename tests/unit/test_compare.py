"""compare_offers ranking."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from allegro_mcp.tools import compare


def _offer(oid: str, price: float, *, seller_id: str, free: bool) -> dict[str, object]:
    return {
        "id": oid,
        "name": oid,
        "sellingMode": {"price": {"amount": str(price), "currency": "PLN"}},
        "seller": {"id": seller_id, "login": f"L-{seller_id}"},
        "stock": {"available": 1},
        "delivery": {"free": free, "options": []},
        "product": {"id": "P"},
    }


@pytest.mark.asyncio
async def test_compare_offers_ranks_by_weights(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://api.allegro.pl.allegrosandbox.pl/sale/product-offers/A",
        json=_offer("A", 100.0, seller_id="1", free=True),
    )
    httpx_mock.add_response(
        url="https://api.allegro.pl.allegrosandbox.pl/sale/product-offers/B",
        json=_offer("B", 150.0, seller_id="2", free=False),
    )
    httpx_mock.add_response(
        url="https://api.allegro.pl.allegrosandbox.pl/users/1",
        json={"id": "1", "login": "best", "ratings": {"average": 5.0, "count": 100}},
    )
    httpx_mock.add_response(
        url="https://api.allegro.pl.allegrosandbox.pl/users/2",
        json={"id": "2", "login": "ok", "ratings": {"average": 3.0, "count": 100}},
    )
    mcp = FastMCP(name="t")
    compare.register(mcp, tool_context)
    tool = await mcp.get_tool("compare_offers")
    table = await tool.fn(offer_ids=["A", "B"])
    assert table.best_offer_id == "A"
    assert table.rows[0].offer_id == "A"
    assert table.rows[0].rank_score is not None
    assert table.weights is not None
    assert sum(table.weights.values()) == pytest.approx(1.0, rel=0.001)
