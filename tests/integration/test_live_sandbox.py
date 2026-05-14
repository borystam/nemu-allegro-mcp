"""Integration tests against the live Allegro sandbox.

These are skipped — not failed — when sandbox credentials are not present in
the environment, so unit-only test runs stay green. CI runs them from a
dedicated workflow gated on repo secrets.

Set the following to enable:

- ALLEGRO_CLIENT_ID, ALLEGRO_CLIENT_SECRET — sandbox app credentials
- ALLEGRO_USER_AGENT — your contact string
- ALLEGRO_ENVIRONMENT=sandbox
- a bootstrapped token DB at ALLEGRO_TOKEN_DB_PATH
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from allegro_mcp.auth.refresh import TokenManager
from allegro_mcp.auth.token_store import TokenStore
from allegro_mcp.client import AllegroClient
from allegro_mcp.config import load_settings
from allegro_mcp.persistence.price_history import PriceHistoryStore
from allegro_mcp.tools import ToolContext

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("ALLEGRO_CLIENT_ID"),
        reason="set ALLEGRO_CLIENT_ID etc. and bootstrap tokens to run",
    ),
]


@pytest_asyncio.fixture
async def live_context() -> AsyncIterator[ToolContext]:
    settings = load_settings()
    store = TokenStore(settings.token_db_path)
    if await store.load() is None:
        pytest.skip("token store empty; run scripts/bootstrap_auth.py first")
    api_http = httpx.AsyncClient(
        base_url=settings.api_base_url,
        http2=True,
        headers={
            "User-Agent": settings.user_agent,
            "Accept": "application/vnd.allegro.public.v1+json",
            "Accept-Language": "pl-PL",
        },
    )
    auth_http = httpx.AsyncClient(base_url=settings.auth_base_url)
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


@pytest.mark.asyncio
async def test_list_categories_returns_top_level(live_context: ToolContext) -> None:
    payload = await live_context.client.get("/sale/categories")
    categories = payload.get("categories") or []
    assert categories, "sandbox should return at least the top-level categories"


@pytest.mark.asyncio
async def test_me_returns_authenticated_account(live_context: ToolContext) -> None:
    payload = await live_context.client.get("/me")
    assert payload.get("login")
