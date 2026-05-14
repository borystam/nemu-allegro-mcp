"""Shared response-shaping helpers.

Allegro responses contain plenty of Polish field names and nested objects. We
flatten them into our Pydantic models here so individual tool modules stay
focused on endpoint semantics rather than JSON spelunking.
"""

from __future__ import annotations

from typing import Any

from allegro_mcp.models.category import Category, CategoryParameter, CategoryParameters
from allegro_mcp.models.offer import Money, Offer, OfferDelivery, OfferSummary
from allegro_mcp.models.product import Product, ProductSearchResult
from allegro_mcp.models.search import SearchFilter, SearchResult
from allegro_mcp.models.seller import Seller, SellerRatings


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def parse_offer_summary(raw: dict[str, Any]) -> OfferSummary:
    """Parse a compact offer record from search results."""
    price = _money_from(raw.get("sellingMode", {}).get("price")) or _money_from(raw.get("price"))
    if price is None:
        price = Money(amount=0.0)
    seller = raw.get("seller") or {}
    delivery = raw.get("delivery") or {}
    category = raw.get("category") or {}
    product_id = None
    if isinstance(raw.get("product"), dict):
        product_id = raw["product"].get("id")
    return OfferSummary(
        offer_id=str(raw.get("id") or raw.get("offerId") or ""),
        name=str(raw.get("name") or raw.get("title") or ""),
        price=price,
        seller_id=_str_or_none(seller.get("id")),
        seller_login=_str_or_none(seller.get("login")),
        condition=_str_or_none(
            _pick_parameter(raw.get("parameters"), "condition") or raw.get("condition")
        ),
        quantity_available=_int_or_none(raw.get("stock", {}).get("available")),
        is_business=_infer_is_business(seller),
        free_delivery=_bool_or_none(delivery.get("free")),
        smart=_bool_or_none(delivery.get("smart")),
        image_url=_first_image(raw.get("images")),
        web_url=_offer_web_url(raw),
        product_id=_str_or_none(product_id),
        category_id=_str_or_none(category.get("id")),
    )


def parse_search_result(
    payload: dict[str, Any], *, offset: int = 0, limit: int = 0
) -> SearchResult:
    """Parse `/offers/listing` shape."""
    items = payload.get("items") or {}
    regular = items.get("regular") or []
    promoted = items.get("promoted") or []
    filters = payload.get("filters") or []
    return SearchResult(
        total_count=int(payload.get("totalCount") or len(regular)),
        offers=[parse_offer_summary(item) for item in regular],
        promoted_offers=[parse_offer_summary(item) for item in promoted],
        filters=[
            SearchFilter(
                id=str(f.get("id") or ""),
                name=str(f.get("name") or ""),
                values=[
                    {"id": str(v.get("value", "")), "name": str(v.get("name", ""))}
                    for v in (f.get("values") or [])
                ],
            )
            for f in filters
        ],
        offset=offset,
        limit=limit,
    )


def parse_offer(raw: dict[str, Any]) -> Offer:
    """Parse a full offer detail response."""
    selling_mode = raw.get("sellingMode") or {}
    price = _money_from(selling_mode.get("price")) or _money_from(raw.get("price"))
    if price is None:
        price = Money(amount=0.0)
    seller = raw.get("seller") or {}
    category = raw.get("category") or {}
    product = raw.get("product") or {}
    images = [img.get("url") for img in raw.get("images") or [] if img.get("url")]
    delivery_raw = raw.get("delivery") or {}
    delivery = OfferDelivery(
        free_delivery=_bool_or_none(delivery_raw.get("free")),
        handling_time=_str_or_none(delivery_raw.get("handlingTime")),
        shipping_rates_id=_str_or_none((delivery_raw.get("shippingRates") or {}).get("id")),
        options=list(delivery_raw.get("options") or []),
    )
    return Offer(
        offer_id=str(raw.get("id") or ""),
        name=str(raw.get("name") or ""),
        description_html=_extract_description(raw.get("description")),
        price=price,
        original_price=_money_from(
            selling_mode.get("priceAutomation", {}).get("rule", {}).get("referencePrice")
        ),
        seller_id=_str_or_none(seller.get("id")),
        seller_login=_str_or_none(seller.get("login")),
        is_business=_infer_is_business(seller),
        condition=_str_or_none(_pick_parameter(raw.get("parameters"), "condition")),
        quantity_available=_int_or_none((raw.get("stock") or {}).get("available")),
        stock_unit=_str_or_none((raw.get("stock") or {}).get("unit")),
        category_id=_str_or_none(category.get("id")),
        category_path=[str(node.get("name")) for node in raw.get("categoryPath") or []],
        product_id=_str_or_none(product.get("id")),
        parameters=list(raw.get("parameters") or []),
        promotion_flags=list(raw.get("promotion", {}).get("packageTypes") or []),
        image_urls=[str(url) for url in images],
        web_url=_offer_web_url(raw),
        delivery=delivery,
    )


def parse_product(raw: dict[str, Any]) -> Product:
    images = []
    for img in raw.get("images") or []:
        if isinstance(img, dict):
            images.append(img.get("url"))
        elif isinstance(img, str):
            images.append(img)
    return Product(
        product_id=str(raw.get("id") or ""),
        name=str(raw.get("name") or ""),
        description=_extract_description(raw.get("description")),
        category_id=_str_or_none((raw.get("category") or {}).get("id")),
        brand=_str_or_none(_pick_parameter(raw.get("parameters"), "brand")),
        image_urls=[str(url) for url in images if url],
        ean=[str(code) for code in (raw.get("ean") or [])],
        parameters=list(raw.get("parameters") or []),
    )


def parse_product_search(
    payload: dict[str, Any], *, phrase: str | None = None
) -> ProductSearchResult:
    products_raw = payload.get("products") or []
    return ProductSearchResult(
        products=[parse_product(p) for p in products_raw],
        total_count=_int_or_none(payload.get("totalCount")),
        query_phrase=phrase,
    )


def parse_category(raw: dict[str, Any]) -> Category:
    return Category(
        category_id=str(raw.get("id") or ""),
        name=str(raw.get("name") or raw.get("nameEn") or raw.get("nameLocalized") or ""),
        name_pl=str(raw.get("name") or ""),
        parent_id=_str_or_none((raw.get("parent") or {}).get("id")),
        leaf=bool(raw.get("leaf") if raw.get("leaf") is not None else not raw.get("children")),
    )


def parse_category_parameters(payload: dict[str, Any], category_id: str) -> CategoryParameters:
    parameters = []
    for raw in payload.get("parameters") or []:
        parameters.append(
            CategoryParameter(
                parameter_id=str(raw.get("id") or ""),
                name=str(raw.get("nameEn") or raw.get("name") or ""),
                name_pl=str(raw.get("name") or ""),
                type=str(raw.get("type") or ""),
                required=bool(raw.get("required") or False),
                restrictions=dict(raw.get("restrictions") or {}),
                dictionary=[
                    {"id": str(v.get("id", "")), "value": str(v.get("value", ""))}
                    for v in (raw.get("dictionary") or [])
                ],
                unit=_str_or_none(raw.get("unit")),
            )
        )
    return CategoryParameters(category_id=category_id, parameters=parameters)


def parse_seller(raw: dict[str, Any]) -> Seller:
    ratings_raw = raw.get("ratings") or raw.get("statistics") or {}
    ratings = SellerRatings(
        average_score=_float_or_none(ratings_raw.get("average")),
        review_count=_int_or_none(ratings_raw.get("count")),
        positive_pct=_float_or_none(ratings_raw.get("positivePercentage")),
        super_seller=bool(raw.get("superSeller") or raw.get("superSellerStatus")),
    )
    return Seller(
        seller_id=str(raw.get("id") or ""),
        login=str(raw.get("login") or ""),
        is_business=_infer_is_business(raw),
        company_name=_str_or_none((raw.get("company") or {}).get("name")),
        location=_str_or_none((raw.get("address") or {}).get("city")),
        member_since=None,
        ratings=ratings,
    )


def _money_from(raw: Any) -> Money | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        amount = _coalesce(raw.get("amount"), raw.get("value"))
        currency = raw.get("currency") or "PLN"
        if amount is None:
            return None
        return Money(amount=float(amount), currency=str(currency))
    return None


def _extract_description(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        sections = raw.get("sections") or []
        chunks: list[str] = []
        for section in sections:
            for item in section.get("items") or []:
                if item.get("type") == "TEXT":
                    chunks.append(str(item.get("content") or ""))
        return "\n".join(chunks) if chunks else None
    return None


def _pick_parameter(parameters: Any, target_id: str) -> str | None:
    if not parameters:
        return None
    for param in parameters:
        if not isinstance(param, dict):
            continue
        if str(param.get("id") or "").lower() == target_id.lower():
            values = param.get("values") or param.get("valuesIds") or []
            if values:
                return str(values[0])
    return None


def _first_image(images: Any) -> str | None:
    if not images:
        return None
    for img in images:
        if isinstance(img, dict) and img.get("url"):
            return str(img["url"])
        if isinstance(img, str):
            return img
    return None


def _offer_web_url(raw: dict[str, Any]) -> str | None:
    offer_id = raw.get("id") or raw.get("offerId")
    if not offer_id:
        return None
    return f"https://allegro.pl/oferta/{offer_id}"


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _infer_is_business(seller: Any) -> bool | None:
    """Return True/False if the data is conclusive, otherwise None.

    Allegro flags business sellers either by a ``company`` block being
    present, or by ``kind == "BUSINESS"``. If neither field is present at
    all we report ``None`` ("unknown") rather than falsely reporting the
    seller as private.
    """
    if not isinstance(seller, dict):
        return None
    company = seller.get("company")
    kind = seller.get("kind")
    if company is not None and isinstance(company, dict) and company.get("name"):
        return True
    if isinstance(kind, str):
        kind_upper = kind.upper()
        if kind_upper == "BUSINESS":
            return True
        if kind_upper in {"PRIVATE", "PERSON", "REGULAR"}:
            return False
    if company is None and kind is None:
        return None
    return False
