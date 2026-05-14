"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest_asyncio
from pydantic import SecretStr

from allegro_mcp.auth.refresh import TokenManager
from allegro_mcp.auth.token_store import StoredTokens, TokenStore
from allegro_mcp.client import AllegroClient
from allegro_mcp.config import Environment, Settings
from allegro_mcp.persistence.price_history import PriceHistoryStore
from allegro_mcp.tools import ToolContext


def make_settings(tmp_path: Path) -> Settings:
    """Construct a fully-populated `Settings` for tests."""
    return Settings(
        client_id=SecretStr("test-client-id"),
        client_secret=SecretStr("test-client-secret"),
        user_agent="allegro-mcp-test/0.1 (you@example.com)",
        environment=Environment.SANDBOX,
        token_db_path=tmp_path / "tokens.db",
        history_db_path=tmp_path / "history.db",
        mcp_port=18765,
        mcp_bind="127.0.0.1",
        default_postal_code="00-001",
        rate_limit_rps=200.0,
        rate_limit_burst=200,
        internal_secret=SecretStr("test-internal-secret"),
    )


@pytest_asyncio.fixture
async def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest_asyncio.fixture
async def populated_token_store(settings: Settings) -> AsyncIterator[TokenStore]:
    store = TokenStore(settings.token_db_path)
    await store.save(
        StoredTokens(
            access_token="initial-access",
            refresh_token="initial-refresh",
            access_expires_at=datetime.now(UTC) + timedelta(hours=1),
            scope="allegro:api:profile:read",
        )
    )
    yield store


@pytest_asyncio.fixture
async def http_transport_pair() -> AsyncIterator[tuple[httpx.AsyncClient, httpx.AsyncClient]]:
    """Two AsyncClients, both backed by the same `httpx.MockTransport`."""
    transport_holder: dict[str, httpx.MockTransport] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        return transport_holder["transport"].handle_request(request)  # pragma: no cover

    api_client = httpx.AsyncClient(
        base_url="https://api.test.invalid",
        headers={"User-Agent": "test"},
        transport=httpx.MockTransport(_handler),
    )
    auth_client = httpx.AsyncClient(
        base_url="https://auth.test.invalid",
        headers={"User-Agent": "test"},
        transport=httpx.MockTransport(_handler),
    )
    yield api_client, auth_client
    await api_client.aclose()
    await auth_client.aclose()


@pytest_asyncio.fixture
async def allegro_client(
    settings: Settings,
    populated_token_store: TokenStore,
    httpx_mock: object,
) -> AsyncIterator[AllegroClient]:
    """An `AllegroClient` whose token cache is pre-populated."""
    auth_http = httpx.AsyncClient(base_url=settings.auth_base_url)
    api_http = httpx.AsyncClient(
        base_url=settings.api_base_url,
        headers={"User-Agent": settings.user_agent},
    )
    manager = TokenManager(
        store=populated_token_store,
        http=auth_http,
        token_endpoint=settings.token_endpoint,
        client_id=settings.client_id.get_secret_value(),
        client_secret=settings.client_secret.get_secret_value(),
    )
    client = AllegroClient(settings=settings, token_manager=manager, http=api_http)
    yield client
    await client.aclose()
    await auth_http.aclose()


@pytest_asyncio.fixture
async def tool_context(settings: Settings, allegro_client: AllegroClient) -> ToolContext:
    history = PriceHistoryStore(settings.history_db_path)
    await history.initialise()
    return ToolContext(client=allegro_client, settings=settings, history=history)
