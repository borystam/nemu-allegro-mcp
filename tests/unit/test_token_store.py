"""Token store tests."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from allegro_mcp.auth.token_store import StoredTokens, TokenStore


def _file_mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.mark.asyncio
async def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.db")
    expiry = datetime.now(UTC) + timedelta(hours=1)
    tokens = StoredTokens(
        access_token="a",
        refresh_token="r",
        access_expires_at=expiry,
        scope="x:y:z",
    )
    await store.save(tokens)
    loaded = await store.load()
    assert loaded is not None
    assert loaded.access_token == "a"
    assert loaded.refresh_token == "r"
    assert abs((loaded.access_expires_at - expiry).total_seconds()) < 1


@pytest.mark.asyncio
async def test_load_returns_none_when_no_file(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "nope.db")
    assert await store.load() is None


@pytest.mark.asyncio
async def test_save_enforces_restrictive_file_mode(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.db")
    await store.save(
        StoredTokens(
            access_token="a",
            refresh_token="r",
            access_expires_at=datetime.now(UTC) + timedelta(hours=1),
            scope="s",
        )
    )
    mode = _file_mode(store.db_path)
    # 0600
    assert mode == 0o600


@pytest.mark.asyncio
async def test_clear_deletes_row(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.db")
    await store.save(
        StoredTokens(
            access_token="a",
            refresh_token="r",
            access_expires_at=datetime.now(UTC) + timedelta(hours=1),
            scope="s",
        )
    )
    await store.clear()
    assert await store.load() is None


@pytest.mark.asyncio
async def test_replaces_existing_row(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "tokens.db")
    expiry = datetime.now(UTC) + timedelta(hours=1)
    await store.save(
        StoredTokens(access_token="a1", refresh_token="r1", access_expires_at=expiry, scope="s")
    )
    await store.save(
        StoredTokens(access_token="a2", refresh_token="r2", access_expires_at=expiry, scope="s")
    )
    loaded = await store.load()
    assert loaded is not None
    assert loaded.access_token == "a2"
    assert loaded.refresh_token == "r2"
