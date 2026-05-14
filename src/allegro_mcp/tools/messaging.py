"""Messaging with sellers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from allegro_mcp.models.messaging import Message, MessageThread

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.tools import ToolContext


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach messaging tools."""

    @mcp.tool
    async def list_messages(
        thread_id: Annotated[
            str | None,
            Field(description="Optional thread to fetch in detail; omit for thread index"),
        ] = None,
    ) -> list[MessageThread]:
        """List message threads, optionally drilling into one.

        Use this to find existing conversations or to read a specific
        thread before composing a reply. Do not use this to poll for new
        messages on a tight loop; respect the rate limiter.
        """
        if thread_id is None:
            payload = await context.client.get("/messaging/threads")
            threads = payload.get("threads") or []
            return [_thread_from(raw) for raw in threads]
        payload = await context.client.get(f"/messaging/threads/{thread_id}/messages")
        messages = payload.get("messages") or []
        thread_meta = payload.get("thread") or {}
        thread = _thread_from(thread_meta or {"id": thread_id})
        thread.messages = [_message_from(m, thread_id) for m in messages]
        return [thread]

    @mcp.tool
    async def send_message(
        thread_id: Annotated[str, Field(description="Thread to post into")],
        body: Annotated[str, Field(min_length=1, max_length=4000)],
    ) -> Message:
        """Post a message into an existing thread.

        Use this for buyer-seller communication: clarifying delivery,
        asking about parameters, confirming an offer is genuine. The
        message body is sent verbatim; the agent should write in the
        user's voice. Do not use this for unrelated outreach or marketing.
        """
        payload = await context.client.post(
            f"/messaging/threads/{thread_id}/messages",
            json={"text": body},
        )
        return _message_from(payload, thread_id)


def _thread_from(raw: dict[str, Any]) -> MessageThread:
    counterparty = raw.get("interlocutor") or {}
    related_offer = (
        (raw.get("relatedObject") or {})
        if raw.get("relatedObject", {}).get("type") == "OFFER"
        else None
    )
    related_order = (
        (raw.get("relatedObject") or {})
        if raw.get("relatedObject", {}).get("type") == "ORDER"
        else None
    )
    last_message_at = _parse_dt(raw.get("lastMessageDateTime"))
    return MessageThread(
        thread_id=str(raw.get("id") or ""),
        counterparty_login=counterparty.get("login"),
        counterparty_id=str(counterparty.get("id") or "") or None,
        subject=raw.get("subject"),
        last_message_at=last_message_at,
        unread_count=int(raw.get("unreadCount") or 0),
        related_offer_id=str((related_offer or {}).get("id") or "") or None,
        related_order_id=str((related_order or {}).get("id") or "") or None,
    )


def _message_from(raw: dict[str, Any], thread_id: str) -> Message:
    author = raw.get("author") or {}
    return Message(
        message_id=str(raw.get("id") or ""),
        thread_id=thread_id,
        author_id=str(author.get("id") or "") or None,
        author_login=author.get("login"),
        body=str(raw.get("text") or ""),
        created_at=_parse_dt(raw.get("createdAt")) or _parse_dt(raw.get("messageDateTime")),
        attachments=list(raw.get("attachments") or []),
    )


def _parse_dt(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))

    return datetime.now(UTC)
