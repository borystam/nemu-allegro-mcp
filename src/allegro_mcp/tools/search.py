"""Phrase-based offer search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field

from allegro_mcp.models.search import SearchResult
from allegro_mcp.tools._parsers import parse_search_result

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.tools import ToolContext


_SORT_VALUES = (
    "relevance",
    "price_asc",
    "price_desc",
    "price_with_delivery_asc",
    "price_with_delivery_desc",
    "popularity",
    "ending_time",
    "starting_time",
)

_SORT_MAP = {
    "relevance": "-relevance",
    "price_asc": "+price",
    "price_desc": "-price",
    "price_with_delivery_asc": "+withDeliveryPrice",
    "price_with_delivery_desc": "-withDeliveryPrice",
    "popularity": "-popularity",
    "ending_time": "+endTime",
    "starting_time": "-startTime",
}

_CONDITION_MAP = {
    "new": "new",
    "used": "used",
    "refurbished": "refurbished",
    "damaged": "damaged",
}


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach `search_offers` and `search_archive` to the server."""

    @mcp.tool
    async def search_offers(
        phrase: Annotated[str, Field(description="Search query, free text")],
        category_id: Annotated[
            str | None, Field(description="Restrict to a category from `list_categories`")
        ] = None,
        price_from: Annotated[float | None, Field(ge=0)] = None,
        price_to: Annotated[float | None, Field(ge=0)] = None,
        condition: Annotated[
            Literal["new", "used", "refurbished", "damaged"] | None,
            Field(description="Filter by item condition"),
        ] = None,
        smart_only: Annotated[bool, Field(description="Restrict to Allegro Smart offers")] = False,
        sort: Annotated[
            Literal[
                "relevance",
                "price_asc",
                "price_desc",
                "price_with_delivery_asc",
                "price_with_delivery_desc",
                "popularity",
                "ending_time",
                "starting_time",
            ],
            Field(description="Result ordering"),
        ] = "relevance",
        limit: Annotated[int, Field(ge=1, le=60)] = 24,
        offset: Annotated[int, Field(ge=0, le=600)] = 0,
    ) -> SearchResult:
        """Search Allegro offers by phrase.

        Use this when you have a concrete query and want the top matches with
        their summaries. Do not use this for barcode lookups (use
        `search_products` with `ean`) or when initial searches return too few
        results (use `expand_search` or `deep_search`).
        """
        if sort not in _SORT_VALUES:
            raise ValueError(f"unsupported sort {sort!r}; expected one of {_SORT_VALUES}")
        params = {
            "phrase": phrase,
            "category.id": category_id,
            "price.from": price_from,
            "price.to": price_to,
            "parameter.11323": _CONDITION_MAP.get(condition) if condition else None,
            "delivery.smart": "true" if smart_only else None,
            "sort": _SORT_MAP[sort],
            "limit": limit,
            "offset": offset,
        }
        payload = await context.client.get("/offers/listing", params=params)
        result = parse_search_result(payload, offset=offset, limit=limit)
        result.sort = sort
        return result

    @mcp.tool
    async def search_archive(
        phrase: Annotated[str, Field(description="Search query")],
        category_id: Annotated[str | None, Field()] = None,
        days_back: Annotated[
            int,
            Field(ge=1, le=365, description="How far back to look in the ended-offers archive"),
        ] = 90,
    ) -> SearchResult:
        """Search ended (closed) offers for price reference and trend analysis.

        Use this when you need historical price context that current listings
        do not provide; do not use it for active purchases since the offers
        returned have already ended.
        """
        params = {
            "phrase": phrase,
            "category.id": category_id,
            "publication.endingFrom": f"-{days_back}d",
            "limit": 60,
        }
        payload = await context.client.get("/offers/listing", params=params)
        result = parse_search_result(payload, offset=0, limit=60)
        result.notes.append(f"archive search, days_back={days_back}")
        return result
