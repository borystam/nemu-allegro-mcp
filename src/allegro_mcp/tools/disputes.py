"""Disputes opened against orders."""

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
        """List disputes the authenticated buyer has open or has closed.

        Use this to surface ongoing buyer-protection cases and their
        statuses. Do not use this to read seller-side disputes; this
        endpoint scope is buyer-only.
        """
        payload = await context.client.get("/sale/disputes")
        return [_dispute_from(raw) for raw in payload.get("disputes") or []]

    @mcp.tool
    async def get_dispute(
        dispute_id: Annotated[str, Field(description="Dispute identifier from `list_disputes`")],
    ) -> Dispute:
        """Fetch the full message history for a dispute.

        Use this when you need the back-and-forth between buyer and seller
        before drafting a follow-up message or escalating to Allegro.
        """
        payload = await context.client.get(f"/sale/disputes/{dispute_id}")
        dispute = _dispute_from(payload)
        messages_payload = await context.client.get(f"/sale/disputes/{dispute_id}/messages")
        dispute.messages = [_message_from(raw) for raw in messages_payload.get("messages") or []]
        return dispute

    @mcp.tool
    async def open_dispute(
        order_id: Annotated[str, Field(description="Order against which to open a dispute")],
        reason: Annotated[
            str,
            Field(
                description="Allegro reason code (e.g. `NOT_RECEIVED`, `INCONSISTENT_WITH_DESCRIPTION`)"
            ),
        ],
        description: Annotated[
            str, Field(min_length=20, max_length=4000, description="Buyer's account of the problem")
        ],
    ) -> Dispute:
        """Open a dispute against an order.

        Use this only when the user has decided to escalate; lighter
        contact (`send_message`) is preferable for first contact. Disputes
        are visible to Allegro and trigger buyer-protection workflows.
        """
        payload = await context.client.post(
            "/sale/disputes",
            json={
                "order": {"id": order_id},
                "subject": {"id": reason},
                "message": {"text": description},
            },
        )
        return _dispute_from(payload)


def _dispute_from(raw: dict[str, Any]) -> Dispute:
    order = raw.get("order") or raw.get("checkoutForm") or {}
    subject = raw.get("subject") or {}
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
