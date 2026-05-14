"""FastMCP wiring and module loader."""

from __future__ import annotations

import logging
from datetime import UTC
from typing import TYPE_CHECKING

import httpx
from fastmcp import FastMCP

from allegro_mcp.auth.refresh import TokenManager
from allegro_mcp.auth.token_store import TokenStore
from allegro_mcp.client import AllegroClient
from allegro_mcp.config import Settings, load_settings
from allegro_mcp.persistence.price_history import PriceHistoryStore, PriceSnapshot
from allegro_mcp.tools import ToolContext, load_all
from allegro_mcp.tools._parsers import parse_offer

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

logger = logging.getLogger(__name__)


def build_server(settings: Settings | None = None) -> tuple[FastMCP, ToolContext]:
    """Construct the `FastMCP` instance and the shared `ToolContext`."""
    settings = settings or load_settings()

    auth_http = httpx.AsyncClient(
        base_url=settings.auth_base_url,
        http2=True,
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={"User-Agent": settings.user_agent},
    )

    api_http = httpx.AsyncClient(
        base_url=settings.api_base_url,
        http2=True,
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={
            "User-Agent": settings.user_agent,
            "Accept": "application/vnd.allegro.public.v1+json",
            "Accept-Language": "pl-PL",
        },
    )

    token_store = TokenStore(settings.token_db_path)
    token_manager = TokenManager(
        store=token_store,
        http=auth_http,
        token_endpoint=settings.token_endpoint,
        client_id=settings.client_id.get_secret_value(),
        client_secret=settings.client_secret.get_secret_value(),
    )
    api_client = AllegroClient(
        settings=settings,
        token_manager=token_manager,
        http=api_http,
    )
    history = PriceHistoryStore(settings.history_db_path)

    mcp = FastMCP(
        name="allegro-mcp",
        instructions=(
            "Buy-side Allegro marketplace tools. Search and compare offers, "
            "retrieve purchase history, message sellers, place auction bids "
            "(with explicit confirmation), submit ratings, manage disputes, "
            "and hand off the final purchase to the user."
        ),
    )
    context = ToolContext(client=api_client, settings=settings, history=history)

    for name, module in load_all(settings.module_list):
        logger.info("Loading tool module %s", name)
        module.register(mcp, context)

    _attach_internal_routes(mcp, context)

    return mcp, context


def _attach_internal_routes(mcp: FastMCP, context: ToolContext) -> None:
    """Register internal HTTP routes alongside the MCP transport."""

    @mcp.custom_route("/internal/snapshot-offers", methods=["POST"])
    async def snapshot_offers(request: Request) -> Response:
        """Record a price snapshot for each offer ID supplied in the body.

        The body must be JSON of the form ``{"offer_ids": ["123", "456"]}``.
        The endpoint is authenticated by the ``X-Internal-Secret`` header
        which must equal ``ALLEGRO_INTERNAL_SECRET``. Operators wire this to
        cron or a systemd timer with the set of offer IDs they want to
        track historically. There is no public Allegro endpoint for the
        user's watch-list, so the MCP cannot derive the list itself.
        """
        import hmac

        from starlette.responses import JSONResponse

        expected = context.settings.internal_secret
        if expected is None:
            return JSONResponse(
                {"error": "internal_secret_not_configured"},
                status_code=503,
            )
        provided = request.headers.get("X-Internal-Secret", "")
        if not hmac.compare_digest(provided, expected.get_secret_value()):
            return JSONResponse({"error": "unauthorised"}, status_code=401)
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001 — body could be empty or malformed
            body = None
        offer_ids = _coerce_offer_ids(body)
        if offer_ids is None:
            return JSONResponse(
                {"error": "expected JSON body of shape {\"offer_ids\": [string, ...]}"},
                status_code=400,
            )
        recorded = await _snapshot_offers(context, offer_ids)
        return JSONResponse({"recorded": recorded, "requested": len(offer_ids)})


def _coerce_offer_ids(body: object) -> list[str] | None:
    if not isinstance(body, dict):
        return None
    raw = body.get("offer_ids")
    if not isinstance(raw, list):
        return None
    out: list[str] = []
    for entry in raw:
        if isinstance(entry, str) and entry.strip():
            out.append(entry.strip())
        elif isinstance(entry, int):
            out.append(str(entry))
    return out


async def _snapshot_offers(context: ToolContext, offer_ids: list[str]) -> int:
    """Append a price snapshot for each offer ID in ``offer_ids``."""
    from datetime import datetime

    snapshots: list[PriceSnapshot] = []
    captured_at = datetime.now(UTC)
    for offer_id in offer_ids:
        try:
            detail = await context.client.get(f"/sale/product-offers/{offer_id}")
            offer = parse_offer(detail)
        except Exception as exc:  # noqa: BLE001 — best-effort polling
            logger.warning("Failed to snapshot offer %s: %s", offer_id, exc)
            continue
        snapshots.append(
            PriceSnapshot(
                offer_id=offer.offer_id,
                product_id=offer.product_id,
                price_amount=offer.price.amount,
                currency=offer.price.currency,
                captured_at=captured_at,
                seller_id=offer.seller_id,
                stock_available=offer.quantity_available,
            )
        )
    return await context.history.record_many(snapshots)


def run() -> None:
    """Run the MCP server over streamable HTTP."""
    settings = load_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    mcp, _context = build_server(settings)
    mcp.run(
        transport="http",
        host=settings.mcp_bind,
        port=settings.mcp_port,
    )
