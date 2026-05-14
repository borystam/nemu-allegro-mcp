"""Interactive device-flow bootstrap.

Run once after configuring `ALLEGRO_CLIENT_ID` and `ALLEGRO_CLIENT_SECRET`.
The script prints the verification URL and user code, polls for completion,
and stores the resulting tokens at `ALLEGRO_TOKEN_DB_PATH`.
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from allegro_mcp.auth.device_flow import DeviceCodeExpired, DeviceFlowClient, DeviceFlowError
from allegro_mcp.auth.token_store import TokenStore
from allegro_mcp.config import load_settings

_SCOPES = " ".join(
    [
        "allegro:api:profile:read",
        "allegro:api:sale:offers:read",
        "allegro:api:orders:read",
        "allegro:api:payments:read",
        "allegro:api:bids",
        "allegro:api:messaging",
        "allegro:api:disputes",
        "allegro:api:ratings",
    ]
)


async def _run() -> int:
    settings = load_settings()
    store = TokenStore(settings.token_db_path)
    await store.initialise()

    async with httpx.AsyncClient(
        base_url=settings.auth_base_url,
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={"User-Agent": settings.user_agent},
    ) as http:
        client = DeviceFlowClient(
            client=http,
            token_endpoint=settings.token_endpoint,
            device_endpoint=settings.device_authorization_endpoint,
            client_id=settings.client_id.get_secret_value(),
            client_secret=settings.client_secret.get_secret_value(),
        )
        try:
            device = await client.request_device_code(scope=_SCOPES)
        except httpx.HTTPStatusError as exc:
            print(
                "Failed to request a device code from Allegro. "
                f"HTTP {exc.response.status_code}: {exc.response.text}",
                file=sys.stderr,
            )
            return 2

        verification = device.verification_uri_complete or device.verification_uri
        print("Open the following URL on any device:")
        print(f"  {verification}")
        if not device.verification_uri_complete:
            print(f"and enter the user code: {device.user_code}")
        print(
            f"The code expires in {device.expires_in} seconds. "
            "This script will poll until you complete the prompt."
        )

        try:
            tokens = await client.poll_for_tokens(device)
        except DeviceCodeExpired:
            print(
                "Device code expired before authorisation. Re-run this script.",
                file=sys.stderr,
            )
            return 3
        except DeviceFlowError as exc:
            print(f"Device flow failed: {exc}", file=sys.stderr)
            return 4

        await store.save(tokens)
        print(f"Tokens stored at {settings.token_db_path}")
        return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
