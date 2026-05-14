"""HTTP client wrapper for Allegro REST API.

Adds: bearer-token injection, rate limiting, retries on 429/5xx, refresh-on-401,
and trace-id exposure in error messages.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from allegro_mcp.auth.refresh import TokenManager
from allegro_mcp.config import Settings
from allegro_mcp.utils.rate_limit import TokenBucket

logger = logging.getLogger(__name__)

_DEFAULT_ACCEPT = "application/vnd.allegro.public.v1+json"
_BACKOFF_SCHEDULE = (0.25, 1.0, 4.0)


class AllegroAPIError(RuntimeError):
    """Wraps an HTTP response surfaced to callers."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        trace_id: str | None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.trace_id = trace_id
        self.payload = payload

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        base = super().__str__()
        if self.trace_id:
            return f"{base} [Trace-Id={self.trace_id}]"
        return base


@dataclass(frozen=True, slots=True)
class _RetryDecision:
    retry: bool
    delay: float
    reason: str


class AllegroClient:
    """Thin async wrapper around `httpx.AsyncClient` for Allegro's REST API."""

    def __init__(
        self,
        *,
        settings: Settings,
        token_manager: TokenManager,
        http: httpx.AsyncClient,
        bucket: TokenBucket | None = None,
    ) -> None:
        self._settings = settings
        self._token_manager = token_manager
        self._http = http
        self._bucket = bucket or TokenBucket(
            rate=settings.rate_limit_rps,
            capacity=settings.rate_limit_burst,
        )

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        token_manager: TokenManager,
        http: httpx.AsyncClient | None = None,
    ) -> AllegroClient:
        """Construct a client with a default `httpx.AsyncClient` if not supplied."""
        client = http or httpx.AsyncClient(
            base_url=settings.api_base_url,
            http2=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={
                "User-Agent": settings.user_agent,
                "Accept": _DEFAULT_ACCEPT,
                "Accept-Language": "pl-PL",
            },
        )
        return cls(settings=settings, token_manager=token_manager, http=client)

    @property
    def http(self) -> httpx.AsyncClient:
        return self._http

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        accept: str | None = None,
    ) -> Any:
        return await self._request("GET", path, params=params, accept=accept)

    async def post(
        self,
        path: str,
        *,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
        accept: str | None = None,
    ) -> Any:
        return await self._request("POST", path, params=params, json=json, accept=accept)

    async def put(
        self,
        path: str,
        *,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
        accept: str | None = None,
    ) -> Any:
        return await self._request("PUT", path, params=params, json=json, accept=accept)

    async def delete(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        accept: str | None = None,
    ) -> Any:
        return await self._request("DELETE", path, params=params, accept=accept)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        accept: str | None = None,
    ) -> Any:
        attempt = 0
        refresh_attempted = False
        while True:
            await self._bucket.acquire()
            access_token = await self._token_manager.access_token()
            headers = {"Authorization": f"Bearer {access_token}"}
            if accept is not None:
                headers["Accept"] = accept
            params_clean = _drop_none(params)
            response = await self._http.request(
                method,
                path,
                params=params_clean,
                json=json,
                headers=headers,
            )
            if response.status_code == 401 and not refresh_attempted:
                refresh_attempted = True
                await self._token_manager.force_refresh()
                continue
            decision = self._retry_decision(response, attempt)
            if not decision.retry:
                return self._unwrap(response)
            logger.info(
                "Retrying %s %s after %.2fs (%s)",
                method,
                path,
                decision.delay,
                decision.reason,
            )
            attempt += 1
            await asyncio.sleep(decision.delay)

    @staticmethod
    def _retry_decision(response: httpx.Response, attempt: int) -> _RetryDecision:
        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            delay = retry_after if retry_after is not None else _backoff(attempt)
            return _RetryDecision(retry=True, delay=delay, reason="429 rate limit")
        if 500 <= response.status_code < 600 and attempt < len(_BACKOFF_SCHEDULE):
            return _RetryDecision(
                retry=True,
                delay=_backoff(attempt),
                reason=f"{response.status_code} server error",
            )
        return _RetryDecision(retry=False, delay=0.0, reason="success-or-final")

    @staticmethod
    def _unwrap(response: httpx.Response) -> Any:
        if response.status_code >= 400:
            payload = _safe_json(response)
            trace_id = response.headers.get("Trace-Id") or response.headers.get("X-Trace-Id")
            raise AllegroAPIError(
                f"Allegro API returned {response.status_code} for {response.request.url}",
                status_code=response.status_code,
                trace_id=trace_id,
                payload=payload,
            )
        if response.status_code == 204 or not response.content:
            return None
        ctype = response.headers.get("Content-Type", "")
        if "json" in ctype.lower():
            return response.json()
        return response.text


def _backoff(attempt: int) -> float:
    base = _BACKOFF_SCHEDULE[min(attempt, len(_BACKOFF_SCHEDULE) - 1)]
    return base + random.uniform(0.0, base * 0.1)  # noqa: S311 (jitter only)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _drop_none(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not params:
        return None
    return {k: v for k, v in params.items() if v is not None}
