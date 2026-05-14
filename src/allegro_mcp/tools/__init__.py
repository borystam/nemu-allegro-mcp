"""Tool modules.

Each module exposes a `register(mcp, context)` function that attaches its
tools to the given `FastMCP` instance. `server.py` loads modules dynamically
based on the `ALLEGRO_MCP_MODULES` setting, which lets sell-side modules be
added later without changing the loader.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.client import AllegroClient
    from allegro_mcp.config import Settings
    from allegro_mcp.persistence.price_history import PriceHistoryStore


@dataclass(slots=True)
class ToolContext:
    """Shared dependencies passed to every tool module's `register` function."""

    client: AllegroClient
    settings: Settings
    history: PriceHistoryStore


class _RegistersTools(Protocol):
    def register(self, mcp: FastMCP, context: ToolContext) -> None:  # pragma: no cover
        ...


def load_module(name: str) -> _RegistersTools:
    """Import a tool module by short name (e.g. `search`)."""
    module = importlib.import_module(f"allegro_mcp.tools.{name}")
    if not hasattr(module, "register"):
        raise RuntimeError(f"tool module {name!r} has no register() function")
    return cast(_RegistersTools, module)


def load_all(names: Iterable[str]) -> list[tuple[str, _RegistersTools]]:
    """Import each named module, returning `(name, module)` pairs."""
    return [(name, load_module(name)) for name in names]
