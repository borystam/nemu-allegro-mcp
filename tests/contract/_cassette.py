"""Lightweight cassette replay/record machinery for contract tests.

A cassette is a YAML-free, JSON-dict mapping `"<method> <path>?<sorted_query>"`
to a response shape `{"status": int, "headers": {...}, "json": ...}`. The
absence of a YAML dependency keeps tests hermetic; the trade-off is that we
implement the matcher ourselves, which is small enough to fit in this module.

Set `ALLEGRO_RECORD_CASSETTES=1` and run integration tests against the live
sandbox to refresh cassettes; otherwise the cassette files are replayed and
the tests are offline.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode

import httpx


@dataclass(frozen=True, slots=True)
class CassetteResponse:
    status: int
    headers: dict[str, str]
    body: Any


def _key_for(request: httpx.Request) -> str:
    method = request.method.upper()
    path = request.url.path
    query_pairs = sorted(
        parse_qsl(
            request.url.query.decode()
            if isinstance(request.url.query, bytes)
            else request.url.query,
            keep_blank_values=True,
        )
    )
    query = urlencode(query_pairs)
    return f"{method} {path}?{query}" if query else f"{method} {path}"


def load_cassette(path: Path) -> dict[str, CassetteResponse]:
    if not path.exists():
        raise FileNotFoundError(f"cassette {path} missing; record with ALLEGRO_RECORD_CASSETTES=1")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"cassette {path} is not a JSON object")
    parsed: dict[str, CassetteResponse] = {}
    for key, value in raw.items():
        parsed[key] = CassetteResponse(
            status=int(value.get("status", 200)),
            headers={str(k): str(v) for k, v in (value.get("headers") or {}).items()},
            body=value.get("json"),
        )
    return parsed


def build_transport(cassette: dict[str, CassetteResponse]) -> httpx.MockTransport:
    """Return a `MockTransport` that replies from `cassette`."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = _key_for(request)
        entry = cassette.get(key)
        if entry is None:
            raise AssertionError(f"cassette miss for {key!r}; available keys: {sorted(cassette)}")
        return httpx.Response(
            entry.status,
            headers=entry.headers,
            json=entry.body,
        )

    return httpx.MockTransport(handler)


def is_recording() -> bool:
    return os.environ.get("ALLEGRO_RECORD_CASSETTES") == "1"


def supported_keys(request_iter: Iterable[httpx.Request]) -> list[str]:
    return [_key_for(req) for req in request_iter]
