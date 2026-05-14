"""deep_search and expand_search behaviour."""

from __future__ import annotations

import re

import pytest
from fastmcp import FastMCP

from allegro_mcp.tools import deep_search


def _offer(idx: int, *, product_id: str | None = None) -> dict[str, object]:
    return {
        "id": str(idx),
        "name": f"item-{idx}",
        "sellingMode": {"price": {"amount": str(idx * 10), "currency": "PLN"}},
        "product": {"id": product_id} if product_id else None,
    }


@pytest.mark.asyncio
async def test_deep_search_merges_branches(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*offers/listing.*"),
        json={
            "items": {"regular": [_offer(1, product_id="P1"), _offer(2, product_id="P1")]},
            "totalCount": 2,
        },
        is_reusable=True,
    )
    mcp = FastMCP(name="t")
    deep_search.register(mcp, tool_context)
    tool = await mcp.get_tool("deep_search")
    result = await tool.fn(phrase="Łódź", budget_seconds=2.0)
    # Diacritic-folded branch should fire; merging by product id collapses dupes.
    assert result.total_unique_offers == 1
    branch_names = {p.name for p in result.paths_taken}
    assert "phrase" in branch_names
    assert "phrase_folded" in branch_names


@pytest.mark.asyncio
async def test_expand_search_records_relaxations(allegro_client, tool_context, httpx_mock) -> None:
    httpx_mock.add_response(
        url=re.compile(r".*offers/listing.*"),
        json={"items": {"regular": [_offer(i) for i in range(1, 6)]}, "totalCount": 5},
        is_reusable=True,
    )
    mcp = FastMCP(name="t")
    deep_search.register(mcp, tool_context)
    tool = await mcp.get_tool("expand_search")
    result = await tool.fn(phrase="aparat cyfrowy Olympus", prior_results_count=0)
    assert result.total_count >= 5
    assert any("offers" in note for note in result.notes)
