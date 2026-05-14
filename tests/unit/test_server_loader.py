"""Module-loader and server-bootstrap tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from allegro_mcp.config import Environment, Settings
from allegro_mcp.server import build_server
from allegro_mcp.tools import load_all, load_module


def _settings(tmp_path: Path, modules: str | None = None) -> Settings:
    return Settings(
        client_id=SecretStr("cid"),
        client_secret=SecretStr("csec"),
        user_agent="ua/0.1 (you@example.com)",
        environment=Environment.SANDBOX,
        token_db_path=tmp_path / "tokens.db",
        history_db_path=tmp_path / "history.db",
        mcp_modules=modules
        or ",".join(
            [
                "search",
                "deep_search",
                "offer",
                "product",
                "category",
                "seller",
                "purchases",
                "watching",
                "messaging",
                "bidding",
                "ratings",
                "disputes",
                "compare",
                "intel",
                "purchase_handoff",
            ]
        ),
    )


def test_load_module_returns_register_callable() -> None:
    module = load_module("search")
    assert hasattr(module, "register")


def test_load_module_rejects_unknown() -> None:
    with pytest.raises(ModuleNotFoundError):
        load_module("does-not-exist")


def test_load_all_preserves_order() -> None:
    pairs = load_all(["search", "offer", "compare"])
    names = [name for name, _ in pairs]
    assert names == ["search", "offer", "compare"]


@pytest.mark.asyncio
async def test_build_server_registers_every_buy_side_tool(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    mcp, _ = build_server(settings)
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    expected = {
        "search_offers",
        "search_archive",
        "search_products",
        "get_product",
        "list_offers_for_product",
        "get_offer",
        "list_categories",
        "get_category_parameters",
        "get_seller",
        "list_seller_offers",
        "deep_search",
        "expand_search",
        "compare_offers",
        "compute_total_cost",
        "find_lower_price",
        "detect_suspicious",
        "seller_trust_signal",
        "price_history",
        "list_watched",
        "watch_offer",
        "unwatch_offer",
        "list_purchases",
        "get_purchase",
        "get_my_account",
        "list_messages",
        "send_message",
        "list_bids",
        "place_bid",
        "submit_rating",
        "list_my_ratings",
        "list_disputes",
        "get_dispute",
        "open_dispute",
        "prepare_purchase",
        "find_pickup_points",
    }
    missing = expected - names
    assert not missing, f"missing tools: {sorted(missing)}"


@pytest.mark.asyncio
async def test_build_server_honours_module_filter(tmp_path: Path) -> None:
    settings = _settings(tmp_path, modules="search,offer")
    mcp, _ = build_server(settings)
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert "search_offers" in names
    assert "get_offer" in names
    assert "list_watched" not in names
