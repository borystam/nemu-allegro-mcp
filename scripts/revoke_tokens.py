"""Revoke and remove locally-stored Allegro tokens."""

from __future__ import annotations

import asyncio
import sys

import httpx

from allegro_mcp.auth.token_store import TokenStore
from allegro_mcp.config import load_settings


async def _run() -> int:
    settings = load_settings()
    store = TokenStore(settings.token_db_path)
    tokens = await store.load()
    if tokens is None:
        print("No tokens to revoke; nothing to do.")
        return 0

    async with httpx.AsyncClient(
        base_url=settings.auth_base_url,
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={"User-Agent": settings.user_agent},
    ) as http:
        for token, hint in (
            (tokens.access_token, "access_token"),
            (tokens.refresh_token, "refresh_token"),
        ):
            response = await http.post(
                settings.revoke_endpoint,
                data={"token": token, "token_type_hint": hint},
                auth=(
                    settings.client_id.get_secret_value(),
                    settings.client_secret.get_secret_value(),
                ),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if response.status_code >= 400:
                print(
                    f"Server refused {hint} revocation: HTTP {response.status_code}",
                    file=sys.stderr,
                )
    await store.clear()
    print("Local tokens cleared; re-run bootstrap_auth.py to authorise again.")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
