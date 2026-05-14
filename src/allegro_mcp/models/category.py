"""Category and category-parameter models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Category(BaseModel):
    """A node in the Allegro category tree."""

    category_id: str
    name: str
    name_pl: str
    parent_id: str | None = None
    leaf: bool = False


class CategoryParameter(BaseModel):
    """A single parameter slot exposed by a category."""

    parameter_id: str
    name: str
    name_pl: str
    type: str
    required: bool = False
    restrictions: dict[str, object] = Field(default_factory=dict)
    dictionary: list[dict[str, str]] = Field(default_factory=list)
    unit: str | None = None


class CategoryParameters(BaseModel):
    """Set of parameter slots for a category."""

    category_id: str
    parameters: list[CategoryParameter]
