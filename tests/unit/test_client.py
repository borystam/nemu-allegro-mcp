"""HTTP client tests: rate-limit, retry, refresh-on-401."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from allegro_mcp.auth.refresh import TokenManager
from allegro_mcp.auth.token_store import StoredTokens, TokenStore
from allegro_mcp.client import AllegroAPIError, AllegroClient
from allegro_mcp.config import Environment, Settings
from allegro_mcp.utils.rate_limit import TokenBucket


async def _make_components(
    tmp_path: Any,
    handler: Any,
    *,
    rate: float = 1000.0,
    burst: int = 100,
) -> tuple[AllegroClient, list[httpx.Request]]:
    settings = Settings(
        client_id=SecretStr("cid"),
        client_secret=SecretStr("csec"),
        user_agent="ua/0.1 (you@example.com)",
        environment=Environment.SANDBOX,
        token_db_path=tmp_path / "tokens.db",
        history_db_path=tmp_path / "history.db",
        rate_limit_rps=rate,
        rate_limit_burst=burst,
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
    seen_requests: list[httpx.Request] = []

    def wrap(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return handler(request, seen_requests)

    api_http = httpx.AsyncClient(
        base_url=settings.api_base_url,
        transport=httpx.MockTransport(wrap),
        headers={"User-Agent": settings.user_agent},
    )
    auth_http = httpx.AsyncClient(
        base_url=settings.auth_base_url,
        transport=httpx.MockTransport(_auth_handler),
    )
    manager = TokenManager(
        store=store,
        http=auth_http,
        token_endpoint=settings.token_endpoint,
        client_id="cid",
        client_secret="csec",
    )
    client = AllegroClient(
        settings=settings,
        token_manager=manager,
        http=api_http,
        bucket=TokenBucket(rate=rate, capacity=burst),
    )
    return client, seen_requests


def _auth_handler(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "access_token": "refreshed",
            "refresh_token": "refreshed-r",
            "expires_in": 3600,
            "scope": "x",
        },
    )


@pytest.mark.asyncio
async def test_get_returns_parsed_json(tmp_path: Any) -> None:
    def handler(_request: httpx.Request, _seen: list[httpx.Request]) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client, requests = await _make_components(tmp_path, handler)
    try:
        result = await client.get("/path")
        assert result == {"ok": True}
        assert requests[0].headers["Authorization"] == "Bearer atok"
        assert requests[0].headers["User-Agent"].startswith("ua/0.1")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_retries_on_429_with_retry_after(tmp_path: Any) -> None:
    def handler(_request: httpx.Request, seen: list[httpx.Request]) -> httpx.Response:
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate"})
        return httpx.Response(200, json={"ok": True})

    client, requests = await _make_components(tmp_path, handler)
    try:
        result = await client.get("/path")
        assert result == {"ok": True}
        assert len(requests) == 2
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_refresh_on_401(tmp_path: Any) -> None:
    def handler(_request: httpx.Request, seen: list[httpx.Request]) -> httpx.Response:
        if len(seen) == 1:
            return httpx.Response(401, headers={"Trace-Id": "abc"})
        return httpx.Response(200, json={"ok": True})

    client, requests = await _make_components(tmp_path, handler)
    try:
        result = await client.get("/path")
        assert result == {"ok": True}
        assert len(requests) == 2
        assert requests[1].headers["Authorization"] == "Bearer refreshed"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_retries_on_5xx(tmp_path: Any) -> None:
    def handler(_request: httpx.Request, seen: list[httpx.Request]) -> httpx.Response:
        if len(seen) <= 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    client, requests = await _make_components(tmp_path, handler)
    try:
        result = await client.get("/path")
        assert result == {"ok": True}
        assert len(requests) == 3
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_surface_trace_id_in_error(tmp_path: Any) -> None:
    def handler(_request: httpx.Request, _seen: list[httpx.Request]) -> httpx.Response:
        return httpx.Response(404, headers={"Trace-Id": "xyz"}, json={"errors": []})

    client, _requests = await _make_components(tmp_path, handler)
    try:
        with pytest.raises(AllegroAPIError) as info:
            await client.get("/missing")
        assert info.value.trace_id == "xyz"
        assert info.value.status_code == 404
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_drops_none_params(tmp_path: Any) -> None:
    def handler(request: httpx.Request, _seen: list[httpx.Request]) -> httpx.Response:
        assert "absent" not in str(request.url)
        assert "kept=1" in str(request.url)
        return httpx.Response(200, json={"ok": True})

    client, _ = await _make_components(tmp_path, handler)
    try:
        await client.get("/path", params={"absent": None, "kept": 1})
    finally:
        await client.aclose()
