"""Offer comparison and total-cost computation."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from allegro_mcp.models.compare import ComparisonRow, ComparisonTable
from allegro_mcp.models.intel import LandedCost
from allegro_mcp.models.offer import Money, Offer
from allegro_mcp.tools._parsers import parse_offer, parse_seller

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.client import AllegroClient
    from allegro_mcp.tools import ToolContext


logger = logging.getLogger(__name__)

_DEFAULT_WEIGHTS = {
    "price": 0.5,
    "delivery": 0.2,
    "seller_score": 0.2,
    "smart": 0.1,
}


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach comparison tools."""

    @mcp.tool
    async def compare_offers(
        offer_ids: Annotated[
            list[str],
            Field(min_length=2, max_length=10, description="Offer IDs to compare side by side"),
        ],
        weights: Annotated[
            dict[str, float] | None,
            Field(
                description=(
                    "Optional weights for ranking. Keys: `price`, `delivery`, "
                    "`seller_score`, `smart`. Values are normalised to sum to 1."
                )
            ),
        ] = None,
    ) -> ComparisonTable:
        """Normalise multiple offers into a side-by-side comparison table.

        Use this once you have a shortlist of offer IDs (e.g. from
        `search_offers` or `deep_search`) and want a ranked comparison
        across price, delivery, and seller quality. Do not use this on a
        single offer.
        """
        offers = await _fetch_offers(context.client, offer_ids)
        weights_normalised = _normalise_weights(weights)
        rows = [await _row_for(context.client, offer) for offer in offers]
        ranked = _rank_rows(rows, weights_normalised)
        return ComparisonTable(
            rows=ranked,
            weights=weights_normalised,
            best_offer_id=ranked[0].offer_id if ranked else None,
            reasoning=_explain_weights(weights_normalised),
        )

    @mcp.tool
    async def compute_total_cost(
        offer_id: Annotated[str, Field(description="Offer to evaluate")],
        delivery_method: Annotated[
            str | None,
            Field(description="Delivery method id from the offer's delivery options"),
        ] = None,
        postal_code: Annotated[
            str | None,
            Field(
                description="Postcode for delivery quote; defaults to `ALLEGRO_DEFAULT_POSTAL_CODE`"
            ),
        ] = None,
        quantity: Annotated[int, Field(ge=1, le=100)] = 1,
    ) -> LandedCost:
        """Compute landed cost (price + delivery) for an offer and postcode.

        Use this to compare true delivered prices when sellers split cost
        between item and shipping. Do not assume this includes import duties
        or seller-specific surcharges; the value reflects what Allegro
        returns from `/sale/delivery-methods`.
        """
        return await _compute_total_cost(
            client=context.client,
            offer_id=offer_id,
            delivery_method=delivery_method,
            postal_code=postal_code or context.settings.default_postal_code,
            quantity=quantity,
        )


async def _fetch_offers(client: AllegroClient, offer_ids: list[str]) -> list[Offer]:
    payloads = await asyncio.gather(
        *(client.get(f"/sale/product-offers/{oid}") for oid in offer_ids),
        return_exceptions=False,
    )
    return [parse_offer(payload) for payload in payloads]


async def _row_for(client: AllegroClient, offer: Offer) -> ComparisonRow:
    seller_score = None
    review_count = None
    super_seller = False
    if offer.seller_id:
        try:
            seller_payload = await client.get(f"/users/{offer.seller_id}")
            seller = parse_seller(seller_payload)
            if seller.ratings:
                seller_score = seller.ratings.average_score
                review_count = seller.ratings.review_count
                super_seller = seller.ratings.super_seller
        except Exception as exc:  # noqa: BLE001
            logger.debug("Seller fetch failed for %s: %s", offer.seller_id, exc)
    delivery_cost = _delivery_cost_from(offer)
    landed = None
    if delivery_cost is not None:
        landed = Money(
            amount=offer.price.amount + delivery_cost.amount,
            currency=offer.price.currency,
        )
    elif offer.delivery and offer.delivery.free_delivery:
        landed = offer.price
    return ComparisonRow(
        offer_id=offer.offer_id,
        name=offer.name,
        price=offer.price,
        delivery_cost=delivery_cost,
        landed_cost=landed,
        seller_login=offer.seller_login,
        seller_score=seller_score,
        seller_review_count=review_count,
        is_business=offer.is_business,
        super_seller=super_seller,
        free_delivery=offer.delivery.free_delivery if offer.delivery else None,
        handling_time=offer.delivery.handling_time if offer.delivery else None,
        condition=offer.condition,
    )


def _delivery_cost_from(offer: Offer) -> Money | None:
    if not offer.delivery:
        return None
    if offer.delivery.free_delivery:
        return Money(amount=0.0, currency=offer.price.currency)
    for option in offer.delivery.options:
        cost = option.get("cost") if isinstance(option, dict) else None
        if isinstance(cost, dict):
            money = cost.get("amount") or cost.get("value")
            if money is not None:
                return Money(amount=float(money), currency=str(cost.get("currency", "PLN")))
    return None


def _normalise_weights(weights: dict[str, float] | None) -> dict[str, float]:
    base = dict(_DEFAULT_WEIGHTS)
    if weights:
        for key, value in weights.items():
            if key in base:
                base[key] = max(0.0, float(value))
    total = sum(base.values()) or 1.0
    return {key: value / total for key, value in base.items()}


def _rank_rows(rows: list[ComparisonRow], weights: dict[str, float]) -> list[ComparisonRow]:
    if not rows:
        return rows
    landed_values = [
        row.landed_cost.amount if row.landed_cost else row.price.amount for row in rows
    ]
    min_landed = min(landed_values)
    max_landed = max(landed_values)
    span = max_landed - min_landed or 1.0
    scores = [row.seller_score or 0.0 for row in rows]
    max_score = max(scores) or 1.0
    enriched: list[ComparisonRow] = []
    for row, landed in zip(rows, landed_values, strict=True):
        normalised_price = 1.0 - ((landed - min_landed) / span)
        delivery_component = 1.0 if (row.free_delivery or row.delivery_cost is None) else 0.5
        seller_component = (row.seller_score or 0.0) / max_score if max_score else 0.0
        smart_component = 1.0 if row.smart else 0.0
        rank = (
            weights["price"] * normalised_price
            + weights["delivery"] * delivery_component
            + weights["seller_score"] * seller_component
            + weights["smart"] * smart_component
        )
        row = row.model_copy(update={"rank_score": round(rank, 4)})
        if row.super_seller:
            row.notes.append("Super-sprzedawca")
        enriched.append(row)
    enriched.sort(
        key=lambda r: (
            -(r.rank_score or 0.0),
            r.landed_cost.amount if r.landed_cost else r.price.amount,
        )
    )
    return enriched


def _explain_weights(weights: dict[str, float]) -> list[str]:
    return [f"{key}: {round(value, 3)}" for key, value in weights.items()]


async def _compute_total_cost(
    *,
    client: AllegroClient,
    offer_id: str,
    delivery_method: str | None,
    postal_code: str | None,
    quantity: int,
) -> LandedCost:
    offer_payload = await client.get(f"/sale/product-offers/{offer_id}")
    offer = parse_offer(offer_payload)
    base = Money(amount=offer.price.amount * quantity, currency=offer.price.currency)
    notes: list[str] = []
    delivery_cost: Money | None = None
    method_used = delivery_method

    if postal_code:
        try:
            quote = await client.get(
                f"/sale/product-offers/{offer_id}/delivery-methods",
                params={"deliveryAddress.postCode": postal_code},
            )
            quotes = quote.get("deliveryMethods") or []
            chosen = None
            if delivery_method:
                for entry in quotes:
                    if entry.get("id") == delivery_method:
                        chosen = entry
                        break
            if chosen is None and quotes:
                chosen = quotes[0]
                method_used = chosen.get("id")
                notes.append("delivery_method not specified; cheapest option selected")
            if chosen is not None:
                price = chosen.get("price") or {}
                amount = price.get("amount")
                if amount is not None:
                    delivery_cost = Money(
                        amount=float(amount), currency=str(price.get("currency", base.currency))
                    )
        except Exception as exc:  # noqa: BLE001 — fall back to offer-level cost
            notes.append(f"delivery quote failed: {exc}")

    if delivery_cost is None:
        fallback = _delivery_cost_from(offer)
        if fallback is not None:
            delivery_cost = fallback
            notes.append("used offer-level delivery cost (no postcode quote)")

    total = Money(
        amount=base.amount + (delivery_cost.amount if delivery_cost else 0.0),
        currency=base.currency,
    )
    return LandedCost(
        offer_id=offer_id,
        base_price=base,
        quantity=quantity,
        delivery_method=method_used,
        delivery_cost=delivery_cost,
        total=total,
        postal_code=postal_code,
        notes=notes,
    )
