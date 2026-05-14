"""Buyer-to-seller ratings."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from allegro_mcp.models.ratings import Rating

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.tools import ToolContext


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach rating tools."""

    @mcp.tool
    async def submit_rating(
        order_id: Annotated[str, Field(description="Order to rate")],
        rating: Annotated[int, Field(ge=1, le=5, description="Star rating, 1-5")],
        comment: Annotated[
            str | None, Field(max_length=500, description="Optional written feedback")
        ] = None,
    ) -> Rating:
        """Submit a star rating and optional comment for a completed order.

        Use this when the user explicitly asks to leave feedback for a
        seller. Ratings are public and influence other buyers' decisions;
        ensure the user has approved the wording.
        """
        body: dict[str, Any] = {
            "order": {"id": order_id},
            "rating": rating,
        }
        if comment:
            body["comment"] = comment
        payload = await context.client.post("/sale/user-ratings", json=body)
        return _rating_from(payload)

    @mcp.tool
    async def list_my_ratings(
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> list[Rating]:
        """List ratings the authenticated buyer has previously submitted.

        Use this to surface the user's own feedback history before they
        leave a new rating, or to gather context for a dispute. Do not use
        this to fetch ratings about a seller — that is part of
        `get_seller`'s output.
        """
        payload = await context.client.get(
            "/sale/user-ratings",
            params={"limit": limit},
        )
        return [_rating_from(item) for item in payload.get("ratings") or []]


def _rating_from(raw: dict[str, Any]) -> Rating:
    order = raw.get("order") or {}
    seller = raw.get("seller") or {}
    submitted = raw.get("submittedAt") or raw.get("createdAt")
    return Rating(
        rating_id=str(raw.get("id") or "") or None,
        order_id=str(order.get("id") or ""),
        seller_id=str(seller.get("id") or "") or None,
        seller_login=seller.get("login"),
        rating=int(raw.get("rating") or 0),
        comment=raw.get("comment"),
        submitted_at=_parse_dt(submitted),
    )


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return None
