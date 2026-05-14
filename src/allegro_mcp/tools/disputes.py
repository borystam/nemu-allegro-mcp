"""Post-purchase issues (Allegro's buyer-side dispute model).

Allegro replaced the legacy sale-side dispute endpoints with
`/post-purchase-issues`. The new model exposes read + message-respond
paths but does not expose a public endpoint to OPEN a new dispute —
buyers initiate from the web UI; the API can only see and respond to
issues that already exist.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from allegro_mcp.models.disputes import Dispute, DisputeMessage

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.tools import ToolContext


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach dispute tools."""

    @mcp.tool
    async def list_disputes() -> list[Dispute]:
        """List post-purchase issues the authenticated buyer has open or closed.

        Use this to surface ongoing buyer-protection cases and their
        statuses. The endpoint is buyer-scoped — seller-side cases are
        not returned here.
        """
        payload = await context.client.get("/post-purchase-issues")
        raw_issues = (
            payload.get("postPurchaseIssues")
            or payload.get("issues")
            or payload.get("disputes")
            or []
        )
        return [_dispute_from(raw) for raw in raw_issues]

    @mcp.tool
    async def get_dispute(
        dispute_id: Annotated[str, Field(description="Issue identifier from `list_disputes`")],
    ) -> Dispute:
        """Fetch the full message history for a post-purchase issue.

        Use this when you need the back-and-forth between buyer and seller
        before drafting a follow-up message or escalating to Allegro.
        """
        payload = await context.client.get(f"/post-purchase-issues/{dispute_id}")
        dispute = _dispute_from(payload)
        messages_payload = await context.client.get(f"/post-purchase-issues/{dispute_id}/messages")
        dispute.messages = [_message_from(raw) for raw in messages_payload.get("messages") or []]
        return dispute


def _dispute_from(raw: dict[str, Any]) -> Dispute:
    order = raw.get("order") or raw.get("checkoutForm") or {}
    subject = raw.get("subject") or raw.get("claimType") or {}
    return Dispute(
        dispute_id=str(raw.get("id") or ""),
        order_id=str(order.get("id") or ""),
        status=str(raw.get("status") or ""),
        reason=str(subject.get("id") or subject.get("name") or ""),
        description=raw.get("description"),
        opened_at=_parse_dt(raw.get("createdAt")) or datetime.now(),
        updated_at=_parse_dt(raw.get("updatedAt")),
    )


def _message_from(raw: dict[str, Any]) -> DisputeMessage:
    return DisputeMessage(
        message_id=str(raw.get("id") or ""),
        author_role=str(raw.get("author", {}).get("role") or raw.get("authorRole") or ""),
        body=str(raw.get("text") or ""),
        created_at=_parse_dt(raw.get("createdAt")) or datetime.now(),
    )


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return None
