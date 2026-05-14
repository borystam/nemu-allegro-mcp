"""Token refresh-and-rotate tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from allegro_mcp.auth.refresh import RefreshError, TokenManager
from allegro_mcp.auth.token_store import StoredTokens, TokenStore


def _store_with_tokens(tmp_path: Path, expiry: datetime) -> TokenStore:
    """Return a populated token store. Caller must `await store.initialise()`."""
    return TokenStore(tmp_path / "tokens.db")


async def _populate(store: TokenStore, expiry: datetime) -> None:
    await store.save(
        StoredTokens(
            access_token="initial-access",
            refresh_token="initial-refresh",
            access_expires_at=expiry,
            scope="x",
        )
    )


def _make_manager(handler: Any, store: TokenStore) -> tuple[TokenManager, httpx.AsyncClient]:
    http = httpx.AsyncClient(
        base_url="https://allegro.test",
        transport=httpx.MockTransport(handler),
    )
    manager = TokenManager(
        store=store,
        http=http,
        token_endpoint="https://allegro.test/auth/oauth/token",
        client_id="cid",
        client_secret="csec",
    )
    return manager, http


@pytest.mark.asyncio
async def test_returns_cached_token_when_not_expiring(tmp_path: Path) -> None:
    store = _store_with_tokens(tmp_path, datetime.now(UTC))
    await _populate(store, datetime.now(UTC) + timedelta(hours=1))

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover - should not run
        raise AssertionError("no refresh expected")

    manager, http = _make_manager(handler, store)
    try:
        token = await manager.access_token()
        assert token == "initial-access"
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_refreshes_when_within_leeway(tmp_path: Path) -> None:
    store = _store_with_tokens(tmp_path, datetime.now(UTC))
    await _populate(store, datetime.now(UTC) + timedelta(minutes=2))
    calls: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(bytes(request.content))
        return httpx.Response(
            200,
            json={
                "access_token": "rotated-access",
                "refresh_token": "rotated-refresh",
                "expires_in": 3600,
                "scope": "x",
            },
        )

    manager, http = _make_manager(handler, store)
    try:
        token = await manager.access_token()
        assert token == "rotated-access"
        assert any(b"grant_type=refresh_token" in c for c in calls)
        stored = await store.load()
        assert stored is not None
        assert stored.refresh_token == "rotated-refresh"
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_invalid_grant_raises_refresh_error(tmp_path: Path) -> None:
    store = _store_with_tokens(tmp_path, datetime.now(UTC))
    await _populate(store, datetime.now(UTC) + timedelta(minutes=1))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    manager, http = _make_manager(handler, store)
    try:
        with pytest.raises(RefreshError):
            await manager.access_token()
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_no_tokens_raises(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.db")

    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not call refresh")

    manager, http = _make_manager(handler, store)
    try:
        with pytest.raises(RefreshError):
            await manager.access_token()
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_force_refresh_always_calls_endpoint(tmp_path: Path) -> None:
    store = _store_with_tokens(tmp_path, datetime.now(UTC))
    await _populate(store, datetime.now(UTC) + timedelta(hours=1))
    calls: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(bytes(request.content))
        return httpx.Response(
            200,
            json={
                "access_token": "forced",
                "refresh_token": "forced-refresh",
                "expires_in": 3600,
                "scope": "x",
            },
        )

    manager, http = _make_manager(handler, store)
    try:
        await manager.access_token()
        assert calls == []
        await manager.force_refresh()
        assert calls and b"grant_type=refresh_token" in calls[0]
    finally:
        await http.aclose()
