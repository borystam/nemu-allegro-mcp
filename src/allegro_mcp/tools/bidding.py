"""Auction bidding tools.

Bids are legally binding on win. `place_bid` therefore guards behind an
explicit `confirm=True` flag — the agent must obtain the user's affirmation
before passing it.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from allegro_mcp.models.bidding import Bid, BidStatus
from allegro_mcp.models.offer import Money

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.tools import ToolContext


class ConfirmationRequired(RuntimeError):
    """Raised when a binding action is invoked without explicit confirmation."""


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach bidding tools."""

    @mcp.tool
    async def list_bids() -> list[Bid]:
        """List active and recent bids for the authenticated account.

        Use this to surface auctions the user is participating in,
        including their outbid/winning status. Do not place new bids from
        this tool; use `place_bid` for that.
        """
        payload = await context.client.get("/bidding/bids")
        return [_bid_from(raw) for raw in payload.get("bids") or []]

    @mcp.tool
    async def place_bid(
        offer_id: Annotated[str, Field(description="Auction offer identifier")],
        amount: Annotated[float, Field(gt=0.0, description="Maximum bid amount, in PLN")],
        confirm: Annotated[
            bool,
            Field(
                description=(
                    "Must be true to actually place the bid. Bids are legally "
                    "binding once the auction closes in the bidder's favour."
                )
            ),
        ] = False,
    ) -> Bid:
        """Place a maximum bid on an auction offer.

        Use this only when the user has explicitly authorised the exact
        amount on this exact offer. The tool refuses to act unless
        `confirm=True`. The agent must surface the binding nature of a
        winning bid to the user before passing the confirmation through.
        Do not use this for Buy-Now offers; those are handed off via
        `prepare_purchase`.
        """
        if not confirm:
            raise ConfirmationRequired(
                "place_bid requires confirm=True; auction bids are legally binding on win"
            )
        payload = await context.client.post(
            "/bidding/offers/{offer_id}/bid".replace("{offer_id}", offer_id),
            json={"maxAmount": {"amount": str(amount), "currency": "PLN"}},
        )
        return _bid_from(payload)


def _bid_from(raw: dict[str, Any]) -> Bid:
    offer = raw.get("offer") or {}
    max_amount = raw.get("maxAmount") or raw.get("maximumBid") or {}
    current = raw.get("currentPrice") or raw.get("price") or {}
    status_raw = (raw.get("status") or "").lower()
    status_map = {
        "winning": BidStatus.WINNING,
        "outbid": BidStatus.OUTBID,
        "won": BidStatus.WON,
        "lost": BidStatus.LOST,
        "ended": BidStatus.ENDED,
    }
    return Bid(
        bid_id=str(raw.get("id") or "") or None,
        offer_id=str(offer.get("id") or raw.get("offerId") or ""),
        offer_name=offer.get("name"),
        maximum_bid=_money(max_amount),
        current_price=_money(current),
        status=status_map.get(status_raw, BidStatus.UNKNOWN),
        placed_at=_parse_dt(raw.get("placedAt")),
        auction_ends_at=_parse_dt(
            raw.get("auctionEndsAt") or offer.get("publication", {}).get("endingAt")
        ),
    )


def _money(raw: Any) -> Money | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        amount = raw.get("amount") or raw.get("value")
        if amount is None:
            return None
        return Money(amount=float(amount), currency=str(raw.get("currency") or "PLN"))
    return None


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return None
