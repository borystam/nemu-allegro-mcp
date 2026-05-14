"""Product catalogue search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from allegro_mcp.models.offer import OfferSummary
from allegro_mcp.models.product import Product, ProductSearchResult
from allegro_mcp.tools._parsers import parse_offer_summary, parse_product, parse_product_search

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.tools import ToolContext


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach product-catalogue tools."""

    @mcp.tool
    async def search_products(
        phrase: Annotated[str | None, Field(description="Free-text product query")] = None,
        ean: Annotated[
            str | None,
            Field(description="Exact EAN/UPC/GTIN to look up; takes priority over phrase"),
        ] = None,
        mode: Annotated[
            Literal["MATCHING", "GTIN"],
            Field(description="`MATCHING` for fuzzy, `GTIN` for exact barcode"),
        ] = "MATCHING",
        category_id: Annotated[str | None, Field()] = None,
        language: Annotated[str, Field()] = "pl-PL",
    ) -> ProductSearchResult:
        """Look up products in Allegro's master catalogue.

        Use this to resolve a barcode (`ean`) to a product, or to find the
        catalogue entry that best matches a phrase. Do not use this if you
        want active offers — call `search_offers` or
        `list_offers_for_product` instead.
        """
        if not phrase and not ean:
            raise ValueError("provide at least one of `phrase` or `ean`")
        params = {
            "phrase": phrase,
            "ean": ean,
            "mode": "GTIN" if ean else mode,
            "category.id": category_id,
            "language": language,
        }
        payload = await context.client.get("/sale/products", params=params)
        return parse_product_search(payload, phrase=phrase or ean)

    @mcp.tool
    async def get_product(
        product_id: Annotated[str, Field(description="Allegro product identifier")],
    ) -> Product:
        """Fetch a single product record by ID.

        Use this when you have a product identifier (from a search or an
        offer) and want the canonical description and parameters.
        """
        payload = await context.client.get(f"/sale/products/{product_id}")
        return parse_product(payload)

    @mcp.tool
    async def list_offers_for_product(
        product_id: Annotated[str, Field(description="Allegro product identifier")],
        sort: Annotated[Literal["price_asc", "price_desc", "popularity"], Field()] = "price_asc",
        limit: Annotated[int, Field(ge=1, le=60)] = 24,
    ) -> list[OfferSummary]:
        """List active offers for a specific catalogue product.

        Use this when you have already identified the product (e.g. via
        `search_products`) and want all sellers of that exact product. Do
        not use this for fuzzy or alternative products.
        """
        sort_map = {
            "price_asc": "+price",
            "price_desc": "-price",
            "popularity": "-popularity",
        }
        params = {
            "product.id": product_id,
            "sort": sort_map[sort],
            "limit": limit,
        }
        payload = await context.client.get("/offers/listing", params=params)
        items = (payload.get("items") or {}).get("regular") or []
        return [parse_offer_summary(item) for item in items]
