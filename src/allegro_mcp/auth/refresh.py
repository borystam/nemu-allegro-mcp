"""Refresh-aware token cache for use by the HTTP client."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from allegro_mcp.auth.token_store import StoredTokens, TokenStore

_REFRESH_LEEWAY = timedelta(minutes=5)


class RefreshError(RuntimeError):
    """Raised when a refresh fails irrecoverably; user must re-bootstrap."""


class TokenManager:
    """Provides bearer access tokens and proactively refreshes them.

    Tokens are cached in memory and persisted to the `TokenStore`. Refresh
    tokens rotate on each exchange, so the new refresh token returned by
    Allegro is persisted alongside the new access token.
    """

    def __init__(
        self,
        *,
        store: TokenStore,
        http: httpx.AsyncClient,
        token_endpoint: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        self._store = store
        self._http = http
        self._token_endpoint = token_endpoint
        self._client_id = client_id
        self._client_secret = client_secret
        self._cached: StoredTokens | None = None
        self._lock = asyncio.Lock()

    async def access_token(self) -> str:
        """Return a valid access token, refreshing it if it is near expiry."""
        async with self._lock:
            if self._cached is None:
                loaded = await self._store.load()
                if loaded is None:
                    raise RefreshError("No tokens stored; run scripts/bootstrap_auth.py first.")
                self._cached = loaded
            if self._is_expiring(self._cached):
                self._cached = await self._refresh(self._cached.refresh_token)
            return self._cached.access_token

    async def force_refresh(self) -> str:
        """Force a refresh regardless of expiry. Used after a 401."""
        async with self._lock:
            if self._cached is None:
                loaded = await self._store.load()
                if loaded is None:
                    raise RefreshError("No tokens stored; run scripts/bootstrap_auth.py first.")
                self._cached = loaded
            self._cached = await self._refresh(self._cached.refresh_token)
            return self._cached.access_token

    @staticmethod
    def _is_expiring(tokens: StoredTokens) -> bool:
        return datetime.now(UTC) >= tokens.access_expires_at - _REFRESH_LEEWAY

    async def _refresh(self, refresh_token: str) -> StoredTokens:
        response = await self._http.post(
            self._token_endpoint,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            auth=(self._client_id, self._client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            payload = _safe_json(response) or {}
            error = payload.get("error", "")
            if error == "invalid_grant":
                raise RefreshError(
                    "Refresh token rejected (invalid_grant); re-run scripts/bootstrap_auth.py."
                )
            raise RefreshError(
                f"Token refresh failed (status={response.status_code}, error={error!r})"
            )
        payload = response.json()
        expires_in = int(payload["expires_in"])
        tokens = StoredTokens(
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            access_expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
            scope=str(payload.get("scope", "")),
        )
        await self._store.save(tokens)
        return tokens


def _safe_json(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict):
        return payload
    return None
