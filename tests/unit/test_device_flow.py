"""Device-flow tests with mocked HTTP."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from allegro_mcp.auth.device_flow import (
    DeviceCodeExpired,
    DeviceFlowClient,
    DeviceFlowError,
)


def _make_client(handler: Any) -> tuple[DeviceFlowClient, httpx.AsyncClient]:
    http = httpx.AsyncClient(
        base_url="https://allegro.test",
        transport=httpx.MockTransport(handler),
    )
    client = DeviceFlowClient(
        client=http,
        token_endpoint="https://allegro.test/auth/oauth/token",
        device_endpoint="https://allegro.test/auth/oauth/device",
        client_id="cid",
        client_secret="csecret",
    )
    return client, http


@pytest.mark.asyncio
async def test_request_device_code_parses_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/oauth/device"
        return httpx.Response(
            200,
            json={
                "device_code": "DC",
                "user_code": "ABC-XYZ",
                "verification_uri": "https://allegro.test/auth",
                "expires_in": 600,
                "interval": 2,
            },
        )

    client, http = _make_client(handler)
    try:
        response = await client.request_device_code("scope-a scope-b")
        assert response.device_code == "DC"
        assert response.user_code == "ABC-XYZ"
        assert response.interval == 2
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_poll_retries_until_authorisation() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        body = bytes(request.content).decode()
        assert "device_code=DC" in body
        if attempts["count"] < 2:
            return httpx.Response(400, json={"error": "authorization_pending"})
        return httpx.Response(
            200,
            json={
                "access_token": "atok",
                "refresh_token": "rtok",
                "expires_in": 3600,
                "scope": "scope",
            },
        )

    client, http = _make_client(handler)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    from allegro_mcp.auth.device_flow import DeviceCodeResponse

    device = DeviceCodeResponse(
        device_code="DC",
        user_code="UC",
        verification_uri="https://allegro.test/auth",
        expires_in=120,
        interval=3,
    )
    try:
        tokens = await client.poll_for_tokens(device, sleep=fake_sleep)
        assert tokens.access_token == "atok"
        assert tokens.refresh_token == "rtok"
        assert sleeps == [3]
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_poll_raises_on_expired_token_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "expired_token"})

    client, http = _make_client(handler)
    from allegro_mcp.auth.device_flow import DeviceCodeResponse

    device = DeviceCodeResponse(
        device_code="DC",
        user_code="UC",
        verification_uri="https://allegro.test/auth",
        expires_in=60,
        interval=1,
    )
    try:
        with pytest.raises(DeviceCodeExpired):
            await client.poll_for_tokens(device, sleep=_no_sleep)
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_poll_raises_on_unknown_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "access_denied"})

    client, http = _make_client(handler)
    from allegro_mcp.auth.device_flow import DeviceCodeResponse

    device = DeviceCodeResponse(
        device_code="DC",
        user_code="UC",
        verification_uri="https://allegro.test/auth",
        expires_in=60,
        interval=1,
    )
    try:
        with pytest.raises(DeviceFlowError):
            await client.poll_for_tokens(device, sleep=_no_sleep)
    finally:
        await http.aclose()


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.mark.asyncio
async def test_poll_handles_non_json_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"oops")

    client, http = _make_client(handler)
    from allegro_mcp.auth.device_flow import DeviceCodeResponse

    device = DeviceCodeResponse(
        device_code="DC",
        user_code="UC",
        verification_uri="https://allegro.test/auth",
        expires_in=60,
        interval=1,
    )
    try:
        with pytest.raises(DeviceFlowError):
            await client.poll_for_tokens(device, sleep=_no_sleep)
    finally:
        await http.aclose()


# Sanity: handler body is parseable.
def test_handler_body_is_json() -> None:
    assert json.loads('{"error": "ok"}')["error"] == "ok"
