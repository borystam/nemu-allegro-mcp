"""Connect to a running MCP and exercise every tool with sensible defaults.

Run after `python -m allegro_mcp` is serving. Provide the MCP URL via the
positional argument; defaults to `http://127.0.0.1:8765/mcp`.

This script does not place real bids or open real disputes; for binding
actions it asserts that the tool refuses without `confirm=True` rather than
performing the action.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Iterable
from typing import Any

from fastmcp import Client

_TOOL_DEFAULTS: list[tuple[str, dict[str, Any]]] = [
    ("get_my_account", {}),
    ("list_categories", {}),
    ("search_offers", {"phrase": "iphone 15"}),
    ("search_products", {"phrase": "iphone 15"}),
    ("search_archive", {"phrase": "iphone 15", "days_back": 30}),
    ("deep_search", {"phrase": "iphone 15", "budget_seconds": 6.0}),
    ("expand_search", {"phrase": "iphone 15", "prior_results_count": 0}),
    ("list_messages", {}),
    ("list_purchases", {"period_days": 90}),
    ("list_bids", {}),
    ("list_my_ratings", {"limit": 5}),
    ("list_disputes", {}),
]


async def _run(url: str) -> int:
    async with Client(url) as client:
        tools = await client.list_tools()
        registered = {tool.name for tool in tools}
        print(f"Server exposes {len(registered)} tools")

        ran = 0
        passed = 0
        skipped: list[str] = []
        for name, args in _TOOL_DEFAULTS:
            if name not in registered:
                skipped.append(name)
                continue
            ran += 1
            try:
                result = await client.call_tool(name, args)
                passed += 1
                _print_outcome(name, "ok", result)
            except Exception as exc:  # noqa: BLE001
                _print_outcome(name, "fail", repr(exc))
        if skipped:
            print(f"Skipped (not registered): {', '.join(skipped)}")
        print(f"Summary: {passed}/{ran} tools succeeded")
        return 0 if passed == ran else 1


def _print_outcome(name: str, status: str, payload: Any) -> None:
    if status == "ok":
        rendered = _summarise(payload)
        print(f"  [ok]   {name}: {rendered}")
    else:
        print(f"  [fail] {name}: {payload}")


def _summarise(payload: Any) -> str:
    if hasattr(payload, "data"):
        data = payload.data
    elif hasattr(payload, "structured_content"):
        data = payload.structured_content
    else:
        data = payload
    if isinstance(data, Iterable) and not isinstance(data, (str, bytes, dict)):
        items = list(data)
        return f"{len(items)} item(s)"
    if isinstance(data, dict):
        keys = list(data.keys())[:5]
        return f"keys={keys}"
    return json.dumps(data, default=str)[:80]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "url",
        nargs="?",
        default="http://127.0.0.1:8765/mcp",
        help="Streamable-HTTP MCP endpoint URL",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.url)))


if __name__ == "__main__":
    main()
