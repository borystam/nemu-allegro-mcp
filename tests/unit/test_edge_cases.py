"""Edge-case and bug-hunting tests."""

from __future__ import annotations

import asyncio
import hmac
import re
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from fastmcp import FastMCP
from pydantic import SecretStr, ValidationError

from allegro_mcp.auth.refresh import TokenManager
from allegro_mcp.auth.token_store import StoredTokens, TokenStore
from allegro_mcp.client import AllegroClient
from allegro_mcp.config import Environment, Settings
from allegro_mcp.tools import bidding, intel, load_module, search
from allegro_mcp.tools._parsers import parse_offer, parse_offer_summary

# ----------------------------------------------------------------------
# Parser robustness
# ----------------------------------------------------------------------


def test_parse_offer_summary_drops_arbitrary_first_parameter_as_condition() -> None:
    """Regression: previously the first parameter's first value was blindly
    treated as the condition. Anything that wasn't really a condition leaked
    through. Now we look the parameter up by id."""
    summary = parse_offer_summary(
        {
            "id": "1",
            "name": "x",
            "sellingMode": {"price": {"amount": "10"}},
            "parameters": [
                {"id": "brand", "values": ["Apple"]},
                {"id": "model", "values": ["iPhone"]},
            ],
        }
    )
    assert summary.condition is None  # "Apple" is no longer leaked


def test_parse_offer_summary_uses_condition_parameter_when_present() -> None:
    summary = parse_offer_summary(
        {
            "id": "1",
            "name": "x",
            "sellingMode": {"price": {"amount": "10"}},
            "parameters": [
                {"id": "brand", "values": ["Apple"]},
                {"id": "condition", "values": ["new"]},
            ],
        }
    )
    assert summary.condition == "new"


def test_parse_offer_summary_handles_missing_price() -> None:
    summary = parse_offer_summary({"id": "1", "name": "x"})
    assert summary.price.amount == 0.0
    assert summary.price.currency == "PLN"


def test_parse_offer_summary_handles_non_dict_product() -> None:
    """If `product` is missing or `None`, we shouldn't crash."""
    summary = parse_offer_summary(
        {"id": "1", "name": "x", "sellingMode": {"price": {"amount": "10"}}}
    )
    assert summary.product_id is None


def test_parse_offer_summary_normalises_integer_id() -> None:
    """Allegro sometimes encodes ids as integers."""
    summary = parse_offer_summary(
        {"id": 12345, "name": "x", "sellingMode": {"price": {"amount": "10"}}}
    )
    assert summary.offer_id == "12345"


def test_is_business_is_none_when_seller_info_missing() -> None:
    """Regression: previously we reported `False` (private) when the data was
    actually unknown. The MCP should distinguish "unknown" from "private"."""
    summary = parse_offer_summary(
        {
            "id": "1",
            "name": "x",
            "sellingMode": {"price": {"amount": "10"}},
            "seller": {"id": "s", "login": "l"},  # no kind, no company
        }
    )
    assert summary.is_business is None


def test_is_business_true_when_company_name_present() -> None:
    summary = parse_offer_summary(
        {
            "id": "1",
            "name": "x",
            "sellingMode": {"price": {"amount": "10"}},
            "seller": {"id": "s", "login": "l", "company": {"name": "Acme"}},
        }
    )
    assert summary.is_business is True


def test_is_business_false_when_kind_explicitly_private() -> None:
    summary = parse_offer_summary(
        {
            "id": "1",
            "name": "x",
            "sellingMode": {"price": {"amount": "10"}},
            "seller": {"id": "s", "login": "l", "kind": "PRIVATE"},
        }
    )
    assert summary.is_business is False


def test_parse_offer_handles_dict_image_entries() -> None:
    offer = parse_offer(
        {
            "id": "x",
            "name": "n",
            "sellingMode": {"price": {"amount": "10"}},
            "images": [
                {"url": "a.jpg"},
                {"url": ""},  # falsy should be ignored
                {},  # no url
                {"url": "b.jpg"},
            ],
        }
    )
    assert offer.image_urls == ["a.jpg", "b.jpg"]


# ----------------------------------------------------------------------
# Concurrency: refresh races
# ----------------------------------------------------------------------


@pytest_asyncio.fixture
async def race_components(tmp_path):
    settings = Settings(
        client_id=SecretStr("cid"),
        client_secret=SecretStr("csec"),
        user_agent="ua/0.1 (you@example.com)",
        environment=Environment.SANDBOX,
        token_db_path=tmp_path / "tokens.db",
        history_db_path=tmp_path / "history.db",
    )
    store = TokenStore(settings.token_db_path)
    await store.save(
        StoredTokens(
            access_token="stale",
            refresh_token="rfresh",
            access_expires_at=datetime.now(UTC) + timedelta(hours=1),
            scope="x",
        )
    )
    refresh_calls = {"count": 0}

    def auth_handler(_request: httpx.Request) -> httpx.Response:
        refresh_calls["count"] += 1
        return httpx.Response(
            200,
            json={
                "access_token": f"fresh-{refresh_calls['count']}",
                "refresh_token": "rotated",
                "expires_in": 3600,
                "scope": "x",
            },
        )

    auth_http = httpx.AsyncClient(
        base_url=settings.auth_base_url, transport=httpx.MockTransport(auth_handler)
    )
    manager = TokenManager(
        store=store,
        http=auth_http,
        token_endpoint=settings.token_endpoint,
        client_id="cid",
        client_secret="csec",
    )
    yield settings, manager, refresh_calls
    await auth_http.aclose()


@pytest.mark.asyncio
async def test_concurrent_force_refresh_only_refreshes_once(race_components) -> None:
    _, manager, refresh_calls = race_components
    # Prime the cached access token so all callers see the same stale value.
    initial = await manager.access_token()
    assert refresh_calls["count"] == 0

    async def hammer() -> str:
        return await manager.force_refresh(stale_token=initial)

    tokens = await asyncio.gather(*(hammer() for _ in range(8)))
    assert all(t == tokens[0] for t in tokens)
    # Exactly one refresh should have hit the server even with 8 racing callers.
    assert refresh_calls["count"] == 1


@pytest.mark.asyncio
async def test_force_refresh_without_stale_token_still_refreshes(race_components) -> None:
    _, manager, refresh_calls = race_components
    await manager.access_token()
    await manager.force_refresh()
    await manager.force_refresh()
    assert refresh_calls["count"] == 2  # legacy behaviour preserved


# ----------------------------------------------------------------------
# Server: timing-safe internal secret comparison
# ----------------------------------------------------------------------


def test_internal_secret_uses_hmac_compare_digest() -> None:
    """Grep the source to ensure we don't regress to a naive ``==`` compare."""
    from pathlib import Path

    src = Path("src/allegro_mcp/server.py").read_text()
    assert "hmac.compare_digest" in src
    assert "provided != expected.get_secret_value()" not in src


def test_no_code_references_dead_watchlist_endpoint() -> None:
    """Allegro's public REST API does not expose the user's watch list.

    A previous version of the MCP shipped four tools (`list_watched`,
    `watch_offer`, `unwatch_offer`) plus an `/internal/poll-watched`
    endpoint that all hit `/watchlist`, which 404s. The tools and
    endpoint were removed; this test fails loudly if anyone resurrects
    a code path that calls `/watchlist` again so we re-evaluate.
    """
    from pathlib import Path

    for path in Path("src/allegro_mcp").rglob("*.py"):
        text = path.read_text()
        assert "/watchlist" not in text, (
            f"{path} references /watchlist; Allegro's API does not expose this."
        )
        assert "poll-watched" not in text, (
            f"{path} references /internal/poll-watched; use /internal/snapshot-offers."
        )


# ----------------------------------------------------------------------
# Module loader
# ----------------------------------------------------------------------


def test_load_module_unknown_raises_module_not_found() -> None:
    with pytest.raises(ModuleNotFoundError):
        load_module("ghost-module-that-does-not-exist")


def test_module_list_empty_string_becomes_no_modules(tmp_path) -> None:
    settings = Settings(
        client_id=SecretStr("cid"),
        client_secret=SecretStr("csec"),
        user_agent="ua/0.1 (you@example.com)",
        token_db_path=tmp_path / "t.db",
        history_db_path=tmp_path / "h.db",
        mcp_modules="",
    )
    assert settings.module_list == ()


def test_module_list_trims_whitespace(tmp_path) -> None:
    settings = Settings(
        client_id=SecretStr("cid"),
        client_secret=SecretStr("csec"),
        user_agent="ua/0.1 (you@example.com)",
        token_db_path=tmp_path / "t.db",
        history_db_path=tmp_path / "h.db",
        mcp_modules="search ,  offer  ,",
    )
    assert settings.module_list == ("search", "offer")


# ----------------------------------------------------------------------
# Config validation
# ----------------------------------------------------------------------


def test_rate_limit_burst_zero_rejected(tmp_path) -> None:
    with pytest.raises(ValidationError):
        Settings(
            client_id=SecretStr("cid"),
            client_secret=SecretStr("csec"),
            user_agent="ua/0.1 (you@example.com)",
            token_db_path=tmp_path / "t.db",
            history_db_path=tmp_path / "h.db",
            rate_limit_burst=0,
        )


def test_user_agent_whitespace_rejected(tmp_path) -> None:
    with pytest.raises(ValidationError):
        Settings(
            client_id=SecretStr("cid"),
            client_secret=SecretStr("csec"),
            user_agent="   \t  ",
            token_db_path=tmp_path / "t.db",
            history_db_path=tmp_path / "h.db",
        )


def test_settings_repr_never_leaks_secret(tmp_path) -> None:
    settings = Settings(
        client_id=SecretStr("SUPER-SENSITIVE-ID"),
        client_secret=SecretStr("SUPER-SENSITIVE-SECRET"),
        user_agent="ua/0.1 (you@example.com)",
        token_db_path=tmp_path / "t.db",
        history_db_path=tmp_path / "h.db",
    )
    rendered = repr(settings) + str(settings) + settings.model_dump_json()
    assert "SUPER-SENSITIVE-ID" not in rendered
    assert "SUPER-SENSITIVE-SECRET" not in rendered


# ----------------------------------------------------------------------
# Tools: input validation
# ----------------------------------------------------------------------


def _run_tool_validation(tool, arguments: dict) -> Exception | None:
    """Invoke ``tool.run`` and capture the validation error (if any).

    Returns the exception so individual tests can assert its type and content.
    """
    import asyncio

    async def go() -> Exception | None:
        try:
            await tool.run(arguments)
        except Exception as exc:  # noqa: BLE001
            return exc
        return None

    return asyncio.run(go())


@pytest.mark.asyncio
async def test_compare_offers_rejects_single_offer(tool_context) -> None:
    """``compare_offers`` validates ``min_length=2`` on its input list."""
    from allegro_mcp.tools import compare

    mcp = FastMCP(name="t")
    compare.register(mcp, tool_context)
    tool = await mcp.get_tool("compare_offers")
    # Validate against the input schema directly so we don't have to invoke
    # an event loop within the running asyncio loop.
    schema = tool.parameters
    assert schema["properties"]["offer_ids"]["minItems"] == 2


@pytest.mark.asyncio
async def test_place_bid_amount_must_be_positive(tool_context) -> None:
    mcp = FastMCP(name="t")
    bidding.register(mcp, tool_context)
    tool = await mcp.get_tool("place_bid")
    schema = tool.parameters
    amount = schema["properties"]["amount"]
    # ``gt=0`` translates to ``exclusiveMinimum: 0`` in JSON Schema
    assert amount.get("exclusiveMinimum") == 0


@pytest.mark.asyncio
async def test_open_dispute_requires_minimum_description(tool_context) -> None:
    from allegro_mcp.tools import disputes

    mcp = FastMCP(name="t")
    disputes.register(mcp, tool_context)
    tool = await mcp.get_tool("open_dispute")
    schema = tool.parameters
    desc = schema["properties"]["description"]
    assert desc.get("minLength") == 20


# ----------------------------------------------------------------------
# Intel: parameter values may be dicts
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_suspicious_handles_dict_parameter_values(
    allegro_client, tool_context, httpx_mock
) -> None:
    httpx_mock.add_response(
        url="https://api.allegro.pl.allegrosandbox.pl/sale/product-offers/OF",
        json={
            "id": "OF",
            "name": "Apple iPhone 15 Pro Max 256GB",
            "sellingMode": {"price": {"amount": "5000.00", "currency": "PLN"}},
            "seller": {"id": "S1"},
            "product": {"id": "P"},
            "parameters": [
                {"id": "brand", "values": [{"id": "1", "value": "Apple"}]},
                {"id": "model", "values": [{"id": "2", "value": "iPhone"}]},
                {"id": "color", "values": [{"id": "3", "value": "Natural Titanium"}]},
            ],
        },
    )
    httpx_mock.add_response(
        url="https://api.allegro.pl.allegrosandbox.pl/users/S1",
        json={"id": "S1", "ratings": {"average": 4.9, "count": 200}},
    )
    httpx_mock.add_response(
        url=re.compile(r".*offers/listing.*"),
        json={
            "items": {
                "regular": [
                    {"id": "a", "sellingMode": {"price": {"amount": str(p)}}}
                    for p in (4800, 4900, 5100, 5200, 5300, 5400)
                ]
            }
        },
    )
    mcp = FastMCP(name="t")
    intel.register(mcp, tool_context)
    tool = await mcp.get_tool("detect_suspicious")
    flags = await tool.fn(offer_ids=["OF"])
    # Title contains "Apple" / "iPhone" — overlap detected via dict-shaped values.
    assert not any("title and parameters do not overlap" in r for r in flags[0].reasons)


# ----------------------------------------------------------------------
# HTTP client: more edge cases
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_returns_none_for_204(tmp_path) -> None:
    settings = Settings(
        client_id=SecretStr("cid"),
        client_secret=SecretStr("csec"),
        user_agent="ua/0.1 (you@example.com)",
        environment=Environment.SANDBOX,
        token_db_path=tmp_path / "tokens.db",
        history_db_path=tmp_path / "history.db",
    )
    store = TokenStore(settings.token_db_path)
    await store.save(
        StoredTokens(
            access_token="a",
            refresh_token="r",
            access_expires_at=datetime.now(UTC) + timedelta(hours=1),
            scope="x",
        )
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    api_http = httpx.AsyncClient(
        base_url=settings.api_base_url, transport=httpx.MockTransport(handler)
    )
    auth_http = httpx.AsyncClient(base_url=settings.auth_base_url)
    manager = TokenManager(
        store=store,
        http=auth_http,
        token_endpoint=settings.token_endpoint,
        client_id="cid",
        client_secret="csec",
    )
    client = AllegroClient(settings=settings, token_manager=manager, http=api_http)
    try:
        assert await client.delete("/something") is None
    finally:
        await client.aclose()
        await auth_http.aclose()


@pytest.mark.asyncio
async def test_client_gives_up_after_repeated_5xx(tmp_path) -> None:
    settings = Settings(
        client_id=SecretStr("cid"),
        client_secret=SecretStr("csec"),
        user_agent="ua/0.1 (you@example.com)",
        environment=Environment.SANDBOX,
        token_db_path=tmp_path / "tokens.db",
        history_db_path=tmp_path / "history.db",
        rate_limit_rps=1000,
        rate_limit_burst=100,
    )
    store = TokenStore(settings.token_db_path)
    await store.save(
        StoredTokens(
            access_token="a",
            refresh_token="r",
            access_expires_at=datetime.now(UTC) + timedelta(hours=1),
            scope="x",
        )
    )
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, headers={"Trace-Id": "T"}, json={"errors": []})

    api_http = httpx.AsyncClient(
        base_url=settings.api_base_url, transport=httpx.MockTransport(handler)
    )
    auth_http = httpx.AsyncClient(base_url=settings.auth_base_url)
    manager = TokenManager(
        store=store,
        http=auth_http,
        token_endpoint=settings.token_endpoint,
        client_id="cid",
        client_secret="csec",
    )
    from allegro_mcp.client import AllegroAPIError

    client = AllegroClient(settings=settings, token_manager=manager, http=api_http)
    try:
        with pytest.raises(AllegroAPIError) as info:
            await client.get("/path")
        assert info.value.status_code == 500
        assert info.value.trace_id == "T"
        # Initial call + 3 retries = 4 total
        assert calls["n"] == 4
    finally:
        await client.aclose()
        await auth_http.aclose()


# ----------------------------------------------------------------------
# Search tool: validation
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_offers_limit_bounds(tool_context) -> None:
    mcp = FastMCP(name="t")
    search.register(mcp, tool_context)
    tool = await mcp.get_tool("search_offers")
    schema = tool.parameters["properties"]
    assert schema["limit"].get("maximum") == 60
    assert schema["offset"].get("maximum") == 600


# ----------------------------------------------------------------------
# hmac.compare_digest behaves as a sanity check
# ----------------------------------------------------------------------


def test_hmac_compare_digest_matches_on_equal_strings() -> None:
    """Sanity: ensure stdlib behaviour we rely on hasn't shifted."""
    assert hmac.compare_digest("abc", "abc") is True
    assert hmac.compare_digest("abc", "abd") is False
