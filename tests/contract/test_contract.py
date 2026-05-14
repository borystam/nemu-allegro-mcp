"""Contract tests: cassette replay against the parsers and tool wrappers.

These tests pin our request shaping and response parsing against
representative sandbox responses. They are hermetic — they replay from JSON
fixtures and do not touch the network. Refresh fixtures with
`ALLEGRO_RECORD_CASSETTES=1` and a populated sandbox token.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastmcp import FastMCP
from pydantic import SecretStr

from allegro_mcp.auth.refresh import TokenManager
from allegro_mcp.auth.token_store import StoredTokens, TokenStore
from allegro_mcp.client import AllegroClient
from allegro_mcp.config import Environment, Settings
from allegro_mcp.persistence.price_history import PriceHistoryStore
from allegro_mcp.tools import ToolContext
from allegro_mcp.tools import category as category_module
from allegro_mcp.tools import offer as offer_module
from allegro_mcp.tools import purchases as purchases_module
from allegro_mcp.tools import search as search_module
from tests.contract._cassette import build_transport, load_cassette

CASSETTE_DIR = Path(__file__).parent / "cassettes"

pytestmark = pytest.mark.contract


@pytest_asyncio.fixture
async def cassette_context(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> AsyncIterator[ToolContext]:
    """Build a `ToolContext` whose transport replays the parametrised cassette."""
    cassette_name = getattr(request, "param", None)
    if cassette_name is None:
        raise RuntimeError("cassette_context requires indirect parametrisation")
    cassette = load_cassette(CASSETTE_DIR / cassette_name)
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
            access_token="atok",
            refresh_token="rtok",
            access_expires_at=datetime.now(UTC) + timedelta(hours=1),
            scope="x",
        )
    )
    transport = build_transport(cassette)
    api_http = httpx.AsyncClient(
        base_url=settings.api_base_url,
        transport=transport,
        headers={
            "User-Agent": settings.user_agent,
            "Accept": "application/vnd.allegro.public.v1+json",
        },
    )
    auth_http = httpx.AsyncClient(
        base_url=settings.auth_base_url,
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                200,
                json={
                    "access_token": "x",
                    "refresh_token": "y",
                    "expires_in": 3600,
                    "scope": "x",
                },
            )
        ),
    )
    manager = TokenManager(
        store=store,
        http=auth_http,
        token_endpoint=settings.token_endpoint,
        client_id=settings.client_id.get_secret_value(),
        client_secret=settings.client_secret.get_secret_value(),
    )
    client = AllegroClient(settings=settings, token_manager=manager, http=api_http)
    history = PriceHistoryStore(settings.history_db_path)
    yield ToolContext(client=client, settings=settings, history=history)
    await client.aclose()
    await auth_http.aclose()


@pytest.mark.parametrize("cassette_context", ["search_offers.json"], indirect=True)
@pytest.mark.asyncio
async def test_replay_search_offers(cassette_context: ToolContext) -> None:
    mcp = FastMCP(name="t")
    search_module.register(mcp, cassette_context)
    tool = await mcp.get_tool("search_offers")
    result = await tool.fn(phrase="test phrase", limit=12)
    assert result.total_count == 2
    assert result.offers[0].offer_id == "10000000001"
    assert result.offers[0].price.amount == 199.0


@pytest.mark.parametrize("cassette_context", ["get_offer.json"], indirect=True)
@pytest.mark.asyncio
async def test_replay_get_offer(cassette_context: ToolContext) -> None:
    mcp = FastMCP(name="t")
    offer_module.register(mcp, cassette_context)
    tool = await mcp.get_tool("get_offer")
    result = await tool.fn(offer_id="10000000001")
    assert result.offer_id == "10000000001"
    assert result.category_path == ["Elektronika", "Telefony"]
    assert result.condition == "new"


@pytest.mark.parametrize("cassette_context", ["list_categories.json"], indirect=True)
@pytest.mark.asyncio
async def test_replay_list_categories(cassette_context: ToolContext) -> None:
    mcp = FastMCP(name="t")
    category_module.register(mcp, cassette_context)
    tool = await mcp.get_tool("list_categories")
    result = await tool.fn()
    assert {c.category_id for c in result} == {"1", "2", "3", "9999"}
    assert any(c.leaf for c in result)


@pytest.mark.parametrize("cassette_context", ["me.json"], indirect=True)
@pytest.mark.asyncio
async def test_replay_me(cassette_context: ToolContext) -> None:
    mcp = FastMCP(name="t")
    purchases_module.register(mcp, cassette_context)
    tool = await mcp.get_tool("get_my_account")
    account = await tool.fn()
    assert account.login == "scrubbed_user"
    assert account.country_code == "PL"
