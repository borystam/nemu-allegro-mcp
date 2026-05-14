"""OAuth device flow client.

See https://developer.allegro.pl/auth/#device-flow for the upstream contract.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, Field

from allegro_mcp.auth.token_store import StoredTokens


class DeviceCodeResponse(BaseModel):
    """Result of the initial device-authorization request."""

    device_code: str
    user_code: str
    verification_uri: str = Field(alias="verification_uri")
    verification_uri_complete: str | None = None
    expires_in: int
    interval: int = 5


class DeviceCodeExpired(RuntimeError):
    """Raised when the user did not authorise within `expires_in` seconds."""


class DeviceFlowError(RuntimeError):
    """Raised when the token endpoint returns an unrecoverable error."""


@dataclass(frozen=True, slots=True)
class _PollOutcome:
    tokens: StoredTokens | None
    keep_polling: bool


class DeviceFlowClient:
    """Interact with Allegro's device-flow endpoints.

    The client is intentionally minimal: it issues the device-authorization
    request, then polls the token endpoint until the user completes the flow
    or the code expires. Storage is the caller's responsibility.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        token_endpoint: str,
        device_endpoint: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        self._client = client
        self._token_endpoint = token_endpoint
        self._device_endpoint = device_endpoint
        self._client_id = client_id
        self._client_secret = client_secret

    async def request_device_code(self, scope: str) -> DeviceCodeResponse:
        """Initiate the flow. Returns the verification URI and a user code."""
        response = await self._client.post(
            self._device_endpoint,
            data={"client_id": self._client_id, "scope": scope},
            auth=(self._client_id, self._client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return DeviceCodeResponse.model_validate(response.json())

    async def poll_for_tokens(
        self,
        device_code: DeviceCodeResponse,
        *,
        sleep: Any = asyncio.sleep,
    ) -> StoredTokens:
        """Poll the token endpoint until the user authorises or the code expires."""
        interval = device_code.interval
        deadline = datetime.now(UTC) + timedelta(seconds=device_code.expires_in)
        while datetime.now(UTC) < deadline:
            outcome = await self._poll_once(device_code.device_code)
            if outcome.tokens is not None:
                return outcome.tokens
            if not outcome.keep_polling:
                raise DeviceFlowError("Device flow rejected by Allegro")
            await sleep(interval)
        raise DeviceCodeExpired(
            "Device code expired before authorisation; re-run the bootstrap script."
        )

    async def _poll_once(self, device_code: str) -> _PollOutcome:
        response = await self._client.post(
            self._token_endpoint,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
            },
            auth=(self._client_id, self._client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code == 200:
            return _PollOutcome(tokens=_tokens_from_payload(response.json()), keep_polling=False)
        payload = _safe_json(response)
        error = (payload or {}).get("error", "")
        if error in {"authorization_pending", "slow_down"}:
            return _PollOutcome(tokens=None, keep_polling=True)
        if error == "expired_token":
            raise DeviceCodeExpired("Device code expired; re-run the bootstrap script.")
        raise DeviceFlowError(
            f"Device flow failed (status={response.status_code}, error={error!r})"
        )


def _safe_json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _tokens_from_payload(payload: dict[str, Any]) -> StoredTokens:
    expires_in = int(payload["expires_in"])
    return StoredTokens(
        access_token=str(payload["access_token"]),
        refresh_token=str(payload["refresh_token"]),
        access_expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        scope=str(payload.get("scope", "")),
    )
