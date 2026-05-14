"""Messaging models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Message(BaseModel):
    """A single message within a thread."""

    message_id: str
    thread_id: str
    author_id: str | None = None
    author_login: str | None = None
    body: str
    created_at: datetime
    attachments: list[dict[str, str]] = Field(default_factory=list)


class MessageThread(BaseModel):
    """A messaging conversation with a counterparty."""

    thread_id: str
    counterparty_login: str | None = None
    counterparty_id: str | None = None
    subject: str | None = None
    last_message_at: datetime | None = None
    unread_count: int = 0
    related_offer_id: str | None = None
    related_order_id: str | None = None
    messages: list[Message] = Field(default_factory=list)
