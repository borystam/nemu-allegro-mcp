"""Dispute models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DisputeMessage(BaseModel):
    """A single message in a dispute thread."""

    message_id: str
    author_role: str
    body: str
    created_at: datetime


class Dispute(BaseModel):
    """A dispute opened on an order."""

    dispute_id: str
    order_id: str
    status: str
    reason: str
    description: str | None = None
    opened_at: datetime
    updated_at: datetime | None = None
    messages: list[DisputeMessage] = Field(default_factory=list)
