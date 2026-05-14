"""Watch-list models."""

from __future__ import annotations

from pydantic import BaseModel


class WatchResult(BaseModel):
    """Outcome of a watch/unwatch action."""

    offer_id: str
    watched: bool
    message: str | None = None
