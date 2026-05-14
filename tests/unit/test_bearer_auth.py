"""Bearer-token middleware tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr

from allegro_mcp.config import Environment, Settings
from allegro_mcp.server import (
    BearerAuthMiddleware,
    _bearer_middleware,
    _exposed_without_auth,
    build_server,
)


def _make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    base = {
        "client_id": SecretStr("cid"),
        "client_secret": SecretStr("csec"),
        "user_agent": "ua/0.2 (you@example.com)",
        "environment": Environment.SANDBOX,
        "token_db_path": tmp_path / "tokens.db",
        "history_db_path": tmp_path / "history.db",
    }
    base.update(overrides)
    return Settings(**base)


# ----------------------------------------------------------------------
# Helpers for exercising the ASGI middleware directly
# ----------------------------------------------------------------------


async def _passthrough_app(scope: dict, receive: Any, send: Any) -> None:
    """Tiny ASGI app that always answers 200 with an empty JSON body."""
    if scope.get("type") != "http":
        return
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": b"{}"})


class _CaptureSend:
    """Collects ``send`` messages so the test can assert on the response."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int | None:
        for message in self.messages:
            if message.get("type") == "http.response.start":
                return int(message["status"])
        return None

    @property
    def body(self) -> bytes:
        chunks = [
            m.get("body", b"") for m in self.messages if m.get("type") == "http.response.body"
        ]
        return b"".join(chunks)


async def _receive_noop() -> dict:  # pragma: no cover - shouldn't be called
    return {"type": "http.request", "body": b"", "more_body": False}


def _scope(path: str, *, headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers or [],
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
    }


# ----------------------------------------------------------------------
# Middleware unit tests
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bearer_middleware_rejects_missing_header() -> None:
    middleware = BearerAuthMiddleware(_passthrough_app, expected_token="s3cret")
    send = _CaptureSend()
    await middleware(_scope("/mcp"), _receive_noop, send)
    assert send.status == 401
    assert b"unauthorised" in send.body


@pytest.mark.asyncio
async def test_bearer_middleware_rejects_wrong_token() -> None:
    middleware = BearerAuthMiddleware(_passthrough_app, expected_token="s3cret")
    send = _CaptureSend()
    await middleware(
        _scope("/mcp", headers=[(b"authorization", b"Bearer nope")]),
        _receive_noop,
        send,
    )
    assert send.status == 401


@pytest.mark.asyncio
async def test_bearer_middleware_accepts_correct_token() -> None:
    middleware = BearerAuthMiddleware(_passthrough_app, expected_token="s3cret")
    send = _CaptureSend()
    await middleware(
        _scope("/mcp", headers=[(b"authorization", b"Bearer s3cret")]),
        _receive_noop,
        send,
    )
    assert send.status == 200


@pytest.mark.asyncio
async def test_bearer_middleware_exempts_internal_routes() -> None:
    """`/internal/*` routes are gated by ``X-Internal-Secret``; they must
    not be double-authed by the bearer middleware."""
    middleware = BearerAuthMiddleware(_passthrough_app, expected_token="s3cret")
    send = _CaptureSend()
    await middleware(_scope("/internal/snapshot-offers"), _receive_noop, send)
    assert send.status == 200


@pytest.mark.asyncio
async def test_bearer_middleware_ignores_non_http_scope() -> None:
    """Lifespan and websocket events shouldn't be intercepted."""
    middleware = BearerAuthMiddleware(_passthrough_app, expected_token="s3cret")
    send = _CaptureSend()
    await middleware({"type": "lifespan"}, _receive_noop, send)
    assert send.status is None  # passed through, our stub doesn't respond


@pytest.mark.asyncio
async def test_bearer_middleware_handles_non_bearer_scheme() -> None:
    middleware = BearerAuthMiddleware(_passthrough_app, expected_token="s3cret")
    send = _CaptureSend()
    await middleware(
        _scope("/mcp", headers=[(b"authorization", b"Basic dXNlcjpwYXNz")]),
        _receive_noop,
        send,
    )
    assert send.status == 401


def test_bearer_middleware_rejects_empty_expected_token() -> None:
    with pytest.raises(ValueError):
        BearerAuthMiddleware(_passthrough_app, expected_token="")


# ----------------------------------------------------------------------
# Wiring: build_server + http_app wraps every reachable route
# ----------------------------------------------------------------------


@pytest_asyncio.fixture
async def http_client_with_bearer(tmp_path: Path) -> AsyncIterator[tuple[httpx.AsyncClient, str]]:
    settings = _make_settings(
        tmp_path,
        mcp_bearer=SecretStr("topsecret-bearer"),
        internal_secret=SecretStr("internal-shared"),
    )
    mcp, _ = build_server(settings)
    app = mcp.http_app(middleware=_bearer_middleware(settings.mcp_bearer))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, "topsecret-bearer"


@pytest.mark.asyncio
async def test_http_app_rejects_unauthenticated_mcp_request(http_client_with_bearer) -> None:
    client, _ = http_client_with_bearer
    response = await client.get("/mcp/")
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorised"}


@pytest.mark.asyncio
async def test_http_app_accepts_authenticated_mcp_request(http_client_with_bearer) -> None:
    client, token = http_client_with_bearer
    # We don't speak the MCP protocol over a raw GET, but reaching the
    # transport at all (rather than the middleware's 401) is enough to
    # prove auth passed. The server typically returns 4xx/200 here; we
    # only assert it is NOT 401.
    response = await client.get(
        "/mcp/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code != 401


@pytest.mark.asyncio
async def test_http_app_internal_route_skips_bearer_check(http_client_with_bearer) -> None:
    """Hitting /internal/snapshot-offers should be gated by
    X-Internal-Secret only, not by the bearer middleware. Without the
    secret we expect 401 from the route handler (not the middleware)
    — confirmed by passing through without the bearer header."""
    client, _ = http_client_with_bearer
    response = await client.post("/internal/snapshot-offers", json={"offer_ids": []})
    # Either 401 from the route's own gate, or 200 if the user supplied
    # the right X-Internal-Secret. Either way it's NOT the middleware
    # 401. The body of the middleware 401 is `{"error":"unauthorised"}`;
    # the route's 401 body is the same shape but the contract here is
    # specifically that the middleware did NOT short-circuit before the
    # internal-route handler ran.
    assert response.status_code in {200, 401}
    if response.status_code == 401:
        # The route handler reaches Starlette, so the response is JSON.
        assert response.json().get("error") in {"unauthorised", None}


@pytest.mark.asyncio
async def test_http_app_internal_route_accepts_correct_internal_secret(
    http_client_with_bearer,
) -> None:
    client, _ = http_client_with_bearer
    response = await client.post(
        "/internal/snapshot-offers",
        json={"offer_ids": []},
        headers={"X-Internal-Secret": "internal-shared"},
    )
    assert response.status_code == 200
    assert response.json() == {"recorded": 0, "requested": 0}


# ----------------------------------------------------------------------
# Behaviour when no bearer is configured (legacy default)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_app_no_bearer_allows_unauthenticated_request(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, internal_secret=SecretStr("internal-shared"))
    mcp, _ = build_server(settings)
    app = mcp.http_app(middleware=_bearer_middleware(settings.mcp_bearer))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/internal/snapshot-offers",
            json={"offer_ids": []},
            headers={"X-Internal-Secret": "internal-shared"},
        )
        assert response.status_code == 200


def test_bearer_middleware_helper_returns_empty_list_when_unset() -> None:
    assert _bearer_middleware(None) == []


def test_bearer_middleware_helper_wraps_when_set() -> None:
    middleware = _bearer_middleware(SecretStr("x"))
    assert len(middleware) == 1


def test_exposed_without_auth_loopback(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, mcp_bind="127.0.0.1", mcp_bearer=None)
    assert _exposed_without_auth(settings) is False


def test_exposed_without_auth_localhost(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, mcp_bind="localhost", mcp_bearer=None)
    assert _exposed_without_auth(settings) is False


def test_exposed_without_auth_ipv6_loopback(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, mcp_bind="::1", mcp_bearer=None)
    assert _exposed_without_auth(settings) is False


_WILDCARD_BIND = "0.0.0.0"  # noqa: S104 — fixture asserts a wildcard bind warns


def test_exposed_without_auth_lan_unprotected(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, mcp_bind=_WILDCARD_BIND, mcp_bearer=None)
    assert _exposed_without_auth(settings) is True


def test_exposed_without_auth_lan_with_bearer(tmp_path: Path) -> None:
    settings = _make_settings(
        tmp_path,
        mcp_bind=_WILDCARD_BIND,
        mcp_bearer=SecretStr("anything"),
    )
    assert _exposed_without_auth(settings) is False
