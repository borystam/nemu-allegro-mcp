"""Category tree and parameter discovery."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from allegro_mcp.models.category import Category, CategoryParameters
from allegro_mcp.tools._parsers import parse_category, parse_category_parameters

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.tools import ToolContext


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach category-related tools."""

    @mcp.tool
    async def list_categories(
        parent_id: Annotated[
            str | None,
            Field(description="Parent category ID; omit to list top-level categories"),
        ] = None,
    ) -> list[Category]:
        """List child categories under the given parent.

        Use this to drill down into Allegro's category tree when you need a
        narrower filter for `search_offers`. Do not use this to look up the
        category of a specific offer — call `get_offer` and read
        `category_path` instead.
        """
        params: dict[str, object] = {}
        if parent_id is not None:
            params["parent.id"] = parent_id
        payload = await context.client.get("/sale/categories", params=params)
        return [parse_category(item) for item in payload.get("categories") or []]

    @mcp.tool
    async def get_category_parameters(
        category_id: Annotated[str, Field(description="Allegro category identifier")],
    ) -> CategoryParameters:
        """List the parameter slots a category supports.

        Use this when you want to know which structured filters are
        meaningful for a category (e.g. brand, screen size) so you can pass
        them to `search_offers`. Do not use this on non-leaf categories
        unless you also drill down with `list_categories`.
        """
        payload = await context.client.get(f"/sale/categories/{category_id}/parameters")
        return parse_category_parameters(payload, category_id=category_id)
