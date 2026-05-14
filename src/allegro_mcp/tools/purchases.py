"""Purchase / order history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from allegro_mcp.models.account import Account
from allegro_mcp.models.offer import Money
from allegro_mcp.models.purchase import Purchase, PurchaseLineItem

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.tools import ToolContext


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach purchase-history tools."""

    @mcp.tool
    async def list_purchases(
        period_days: Annotated[int, Field(ge=1, le=365)] = 90,
        status: Annotated[
            str | None,
            Field(
                description="Filter by checkout-form status (e.g. `BOUGHT`, `READY_FOR_PROCESSING`)"
            ),
        ] = None,
    ) -> list[Purchase]:
        """List the authenticated account's recent purchases.

        Use this to find orders for follow-up actions: leaving ratings,
        opening disputes, or referencing in messages to sellers. Do not
        use this as a general history endpoint — Allegro paginates and
        the window is bounded.
        """
        since = (datetime.now(UTC) - timedelta(days=period_days)).isoformat()
        params: dict[str, Any] = {"updatedAt.gte": since}
        if status:
            params["status"] = status
        payload = await context.client.get("/order/checkout-forms", params=params)
        forms = payload.get("checkoutForms") or []
        return [_purchase_from_form(form) for form in forms]

    @mcp.tool
    async def get_purchase(
        order_id: Annotated[str, Field(description="Allegro order / checkout-form identifier")],
    ) -> Purchase:
        """Fetch the full record for a single order.

        Use this once you know the order ID (from `list_purchases`) and
        need its line items, delivery details, or payment status.
        """
        payload = await context.client.get(f"/order/checkout-forms/{order_id}")
        return _purchase_from_form(payload)

    @mcp.tool
    async def get_my_account() -> Account:
        """Return the authenticated user's account profile.

        Use this when the agent needs the user's login or business status
        to phrase a message or evaluate a buyer-protection scenario. Do
        not use this for personally-identifying data beyond what the
        account itself exposes — Allegro returns only a limited profile.
        """
        payload = await context.client.get("/me")
        return Account(
            account_id=str(payload.get("id") or ""),
            login=str(payload.get("login") or ""),
            email=payload.get("email"),
            first_name=payload.get("firstName"),
            last_name=payload.get("lastName"),
            company_name=(payload.get("company") or {}).get("name")
            if payload.get("company")
            else None,
            is_business=payload.get("company") is not None,
            country_code=payload.get("countryCode"),
        )


def _purchase_from_form(form: dict[str, Any]) -> Purchase:
    line_items = []
    for item in form.get("lineItems") or []:
        offer = item.get("offer") or {}
        price = item.get("price") or {}
        line_items.append(
            PurchaseLineItem(
                offer_id=str(offer.get("id") or ""),
                name=str(offer.get("name") or ""),
                quantity=int(item.get("quantity") or 1),
                unit_price=Money(
                    amount=float(price.get("amount") or 0.0),
                    currency=str(price.get("currency") or "PLN"),
                ),
                total_price=(
                    Money(
                        amount=float((item.get("reconciliation") or {}).get("value") or 0.0)
                        or float(price.get("amount") or 0.0) * float(item.get("quantity") or 1),
                        currency=str(price.get("currency") or "PLN"),
                    )
                ),
                seller_id=str((form.get("seller") or {}).get("id") or "") or None,
                seller_login=str((form.get("seller") or {}).get("login") or "") or None,
            )
        )
    summary = form.get("summary") or {}
    total = summary.get("totalToPay") or {}
    delivery = form.get("delivery") or {}
    payment = form.get("payment") or {}
    return Purchase(
        order_id=str(form.get("id") or ""),
        status=str(form.get("status") or ""),
        created_at=_parse_dt(form.get("createdAt")),
        updated_at=_parse_dt(form.get("updatedAt")),
        line_items=line_items,
        total_price=Money(
            amount=float(total.get("amount") or 0.0),
            currency=str(total.get("currency") or "PLN"),
        )
        if total
        else None,
        delivery_address_summary=_address_summary(delivery.get("address") or {}),
        delivery_method=(delivery.get("method") or {}).get("name"),
        payment_status=payment.get("finishedAt") and "finished" or payment.get("type"),
    )


def _parse_dt(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return datetime.now(UTC)


def _address_summary(address: dict[str, Any]) -> str | None:
    parts = [
        address.get("street"),
        address.get("zipCode"),
        address.get("city"),
        address.get("countryCode"),
    ]
    rendered = ", ".join(p for p in parts if p)
    return rendered or None
