"""Intelligence layer: suspicion detection, trust signals, price history."""

from __future__ import annotations

import asyncio
import statistics
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from allegro_mcp.models.intel import (
    PriceHistory,
    PricePoint,
    SuspicionFlag,
    TrustSignal,
)
from allegro_mcp.models.offer import Money, Offer, OfferSummary
from allegro_mcp.tools._parsers import parse_offer, parse_offer_summary, parse_seller

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.client import AllegroClient
    from allegro_mcp.tools import ToolContext


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach intel tools."""

    @mcp.tool
    async def detect_suspicious(
        offer_ids: Annotated[
            list[str],
            Field(min_length=1, max_length=10, description="Offers to inspect"),
        ],
    ) -> list[SuspicionFlag]:
        """Flag offers that look risky: price outliers, new sellers, low reviews.

        Use this on a candidate shortlist before suggesting a purchase. Do
        not treat the absence of a flag as a guarantee of authenticity; this
        is a screen, not a verdict.
        """
        offers = await _fetch_offers(context.client, offer_ids)
        flags = await asyncio.gather(*(_flag_offer(context.client, offer) for offer in offers))
        return list(flags)

    @mcp.tool
    async def seller_trust_signal(
        seller_id: Annotated[str, Field(description="Allegro seller identifier")],
    ) -> TrustSignal:
        """Composite trust score for a seller, with reasoning.

        Use this when deciding whether to buy from a seller you have not
        used before. The score is heuristic; combine it with `detect_suspicious`
        on the specific offer and your own judgement.
        """
        payload = await context.client.get(f"/users/{seller_id}")
        seller = parse_seller(payload)
        components: dict[str, float] = {}
        notes: list[str] = []

        rating = seller.ratings
        components["rating"] = (rating.average_score or 0.0) / 5.0 if rating else 0.0
        review_count = (rating.review_count or 0) if rating else 0
        components["volume"] = min(1.0, review_count / 500.0)
        components["super_seller"] = 1.0 if rating and rating.super_seller else 0.0
        components["business"] = 1.0 if seller.is_business else 0.0
        if rating is None or review_count < 50:
            notes.append("fewer than 50 ratings; treat any score with caution")
        if not seller.is_business:
            notes.append("private seller; consumer protections still apply but recourse is slower")
        score = (
            0.4 * components["rating"]
            + 0.3 * components["volume"]
            + 0.2 * components["super_seller"]
            + 0.1 * components["business"]
        )
        band = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return TrustSignal(
            seller_id=seller_id,
            score=round(score, 3),
            band=band,
            components={k: round(v, 3) for k, v in components.items()},
            notes=notes,
        )

    @mcp.tool
    async def price_history(
        offer_id_or_product_id: Annotated[
            str,
            Field(description="Either an offer ID or a product ID; offers take precedence"),
        ],
        days: Annotated[int, Field(ge=1, le=365)] = 90,
    ) -> PriceHistory:
        """Return locally-recorded price history.

        Use this to detect dips, durable price drops, or recent inflation
        against the offer/product's own history. History is only populated
        for items that have been watched and polled via the
        `/internal/poll-watched` endpoint (or whichever scheduler the
        operator has wired up). Do not assume coverage extends to offers
        the user has never watched.
        """
        now = datetime.now(UTC)
        since = now - timedelta(days=days)
        history_rows = await context.history.read(offer_id_or_product_id, since)
        points = [
            PricePoint(
                captured_at=row.captured_at,
                price=Money(amount=row.price_amount, currency=row.currency),
                stock_available=row.stock_available,
            )
            for row in history_rows
        ]
        prices = [p.price.amount for p in points]
        notes: list[str] = []
        if not points:
            notes.append("no history recorded; poll the offer via /internal/poll-watched")
        median = statistics.median(prices) if prices else None
        lowest = min(prices) if prices else None
        highest = max(prices) if prices else None
        current = points[-1].price if points else None
        delta_pct = None
        if current and lowest is not None and lowest > 0:
            delta_pct = round(((current.amount - lowest) / lowest) * 100.0, 2)
        dip = bool(current and median is not None and current.amount < median * 0.9)
        return PriceHistory(
            offer_id=history_rows[0].offer_id if history_rows else None,
            product_id=history_rows[0].product_id if history_rows else None,
            window_days=days,
            points=points,
            current_price=current,
            median_price=Money(amount=median, currency=points[-1].price.currency)
            if median is not None and points
            else None,
            lowest_ever_price=Money(amount=lowest, currency=points[-1].price.currency)
            if lowest is not None and points
            else None,
            highest_ever_price=Money(amount=highest, currency=points[-1].price.currency)
            if highest is not None and points
            else None,
            delta_vs_lowest_pct=delta_pct,
            dip_detected=dip,
            notes=notes,
        )

    @mcp.tool
    async def find_lower_price(
        reference_offer_id: Annotated[
            str, Field(description="Offer whose product should be repriced")
        ],
        max_rating_drop: Annotated[
            float,
            Field(
                ge=0.0,
                le=5.0,
                description="Max acceptable rating drop versus the reference seller",
            ),
        ] = 5.0,
    ) -> list[OfferSummary]:
        """Find cheaper offers for the same product, subject to a quality floor.

        Use this after picking a candidate offer to confirm there is not a
        materially better deal for the same product. Returns up to 20
        sellers cheaper than the reference, each within `max_rating_drop`
        of the reference seller's rating. Do not use this if the user
        cares about non-price factors that are not modelled here (warranty
        bundles, accessories, etc.) — call `compare_offers` for nuance.
        """
        offer_payload = await context.client.get(f"/sale/product-offers/{reference_offer_id}")
        reference: Offer = parse_offer(offer_payload)
        if not reference.product_id:
            return []
        listings = await context.client.get(
            "/offers/listing",
            params={
                "product.id": reference.product_id,
                "sort": "+price",
                "limit": 30,
            },
        )
        items = (listings.get("items") or {}).get("regular") or []
        candidates = [parse_offer_summary(item) for item in items]

        reference_rating = await _seller_rating(context.client, reference.seller_id)
        cheaper: list[OfferSummary] = []
        for candidate in candidates:
            if candidate.offer_id == reference.offer_id:
                continue
            if candidate.price.amount >= reference.price.amount:
                continue
            rating = await _seller_rating(context.client, candidate.seller_id)
            if (
                reference_rating is not None
                and rating is not None
                and reference_rating - rating > max_rating_drop
            ):
                continue
            cheaper.append(candidate)
            if len(cheaper) >= 20:
                break
        return cheaper


async def _fetch_offers(client: AllegroClient, offer_ids: list[str]) -> list[Offer]:
    payloads = await asyncio.gather(
        *(client.get(f"/sale/product-offers/{oid}") for oid in offer_ids)
    )
    return [parse_offer(p) for p in payloads]


async def _flag_offer(client: AllegroClient, offer: Offer) -> SuspicionFlag:
    reasons: list[str] = []
    signals: dict[str, object] = {}

    rating = None
    review_count = None
    if offer.seller_id:
        try:
            seller_payload = await client.get(f"/users/{offer.seller_id}")
            seller = parse_seller(seller_payload)
            if seller.ratings:
                rating = seller.ratings.average_score
                review_count = seller.ratings.review_count
        except Exception:  # noqa: BLE001
            reasons.append("seller profile unavailable")
    signals["seller_rating"] = rating
    signals["seller_review_count"] = review_count

    if review_count is not None and review_count < 50:
        reasons.append(f"seller has only {review_count} reviews (<50)")

    if offer.product_id:
        try:
            comparable = await client.get(
                "/offers/listing",
                params={"product.id": offer.product_id, "sort": "+price", "limit": 30},
            )
            prices = [
                float((item.get("sellingMode") or {}).get("price", {}).get("amount") or 0.0)
                for item in (comparable.get("items") or {}).get("regular") or []
            ]
            prices = [p for p in prices if p > 0.0]
            if prices and offer.price.amount > 0:
                median = statistics.median(prices)
                if len(prices) >= 5:
                    stdev = statistics.pstdev(prices) or median * 0.1
                    if (median - offer.price.amount) > 3.0 * stdev:
                        reasons.append(
                            f"price {offer.price.amount} is >3σ below product median {round(median, 2)}"
                        )
                signals["product_median_price"] = round(median, 2)
                signals["product_observed_offers"] = len(prices)
        except Exception:  # noqa: BLE001
            reasons.append("product comparable listing unavailable")

    if offer.delivery and offer.delivery.free_delivery and offer.price.amount < 5.0:
        reasons.append("free delivery on near-zero-priced item")

    if offer.name and offer.parameters:
        name_lower = offer.name.lower()
        for param in offer.parameters:
            values = param.get("values") if isinstance(param, dict) else None
            if not values:
                continue
            for value in values:
                if isinstance(value, str) and value.lower() in name_lower:
                    break
            else:
                continue
            break
        else:
            # No overlap between parameter values and the offer name — possible
            # title vs spec mismatch.
            if len(offer.parameters) >= 3:
                reasons.append("title and parameters do not overlap; verify the listing")

    severity = "high" if len(reasons) >= 3 else "medium" if len(reasons) >= 1 else "low"
    return SuspicionFlag(
        offer_id=offer.offer_id,
        severity=severity,
        reasons=reasons,
        signals=signals,
    )


async def _seller_rating(client: AllegroClient, seller_id: str | None) -> float | None:
    if not seller_id:
        return None
    try:
        payload = await client.get(f"/users/{seller_id}")
    except Exception:  # noqa: BLE001
        return None
    seller = parse_seller(payload)
    if seller.ratings and seller.ratings.average_score is not None:
        return float(seller.ratings.average_score)
    return None
