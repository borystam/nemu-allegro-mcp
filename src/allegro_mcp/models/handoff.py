"""Purchase-handoff models."""

from __future__ import annotations

from pydantic import BaseModel


class PurchaseHandoff(BaseModel):
    """A handoff payload to complete the purchase outside the agent.

    The MCP never calls a payment endpoint because Allegro does not expose one
    publicly. This model surfaces the URLs and notes the agent should present
    to the human user so they can complete the transaction themselves.
    """

    offer_id: str
    quantity: int
    web_url: str
    app_deep_link: str
    note: str
