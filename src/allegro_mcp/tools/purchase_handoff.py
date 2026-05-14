"""Handoff to the Allegro web/app for the actual purchase.

The MCP never calls a payment endpoint — Allegro does not expose one in
its public REST API. We construct the deep link and the web URL and let
the human complete the transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from allegro_mcp.models.handoff import PurchaseHandoff
from allegro_mcp.models.pickup import PickupPoint

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.tools import ToolContext


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach purchase-handoff and pickup-point tools."""

    @mcp.tool
    async def prepare_purchase(
        offer_id: Annotated[str, Field(description="Offer the user intends to buy")],
        quantity: Annotated[int, Field(ge=1, le=100)] = 1,
    ) -> PurchaseHandoff:
        """Return URLs the user can follow to complete the purchase.

        Use this once the user has chosen an offer. Allegro's public API
        does not expose a payment endpoint, so the agent cannot complete
        the purchase itself. The user finishes the flow in the Allegro
        web or mobile app via the URLs returned here.
        """
        web_url = f"https://allegro.pl/oferta/{offer_id}?quantity={quantity}"
        deep_link = f"allegro://offer/{offer_id}?quantity={quantity}"
        note = (
            "The Allegro public API does not expose payment endpoints. "
            "Follow the web URL or the deep link in the Allegro app to complete the purchase."
        )
        return PurchaseHandoff(
            offer_id=offer_id,
            quantity=quantity,
            web_url=web_url,
            app_deep_link=deep_link,
            note=note,
        )

    @mcp.tool
    async def find_pickup_points(
        postal_code: Annotated[str, Field(description="Polish postal code, e.g. 00-001")],
        radius_km: Annotated[int, Field(ge=1, le=50)] = 5,
        providers: Annotated[
            list[str] | None,
            Field(description='Optional provider filter (e.g. `["INPOST"]`)'),
        ] = None,
    ) -> list[PickupPoint]:
        """List nearby pickup points (lockers, kiosks) for delivery selection.

        Use this when the user prefers locker/pickup delivery over courier.
        The list is sorted by distance ascending. Do not use this to gauge
        coverage of a country — it returns local points only.
        """
        params: dict[str, Any] = {
            "postCode": postal_code,
            "radius": radius_km,
        }
        if providers:
            params["provider"] = ",".join(providers)
        payload = await context.client.get("/order/pickup-points", params=params)
        raw_points = payload.get("pickupPoints") or payload.get("points") or []
        return [_pickup_from(raw) for raw in raw_points]


def _pickup_from(raw: dict[str, Any]) -> PickupPoint:
    coords = raw.get("location") or raw.get("coordinates") or {}
    address = raw.get("address") or {}
    return PickupPoint(
        point_id=str(raw.get("id") or ""),
        provider=str(raw.get("provider") or raw.get("operator") or ""),
        name=str(raw.get("name") or ""),
        address=str(address.get("street") or raw.get("address1") or ""),
        postal_code=str(address.get("zipCode") or raw.get("postalCode") or ""),
        city=str(address.get("city") or raw.get("city") or ""),
        country_code=str(address.get("countryCode") or "PL"),
        latitude=_float_or_none(coords.get("latitude")),
        longitude=_float_or_none(coords.get("longitude")),
        opening_hours=[str(x) for x in (raw.get("openingHours") or [])],
        distance_km=_float_or_none(raw.get("distance")),
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
