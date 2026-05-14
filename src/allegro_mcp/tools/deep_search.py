"""Parallel multi-branch search.

`deep_search` and `expand_search` exist because small open-weight agents
(e.g. Qwen) lose accuracy past four or five tool hops. By fanning out
inside one tool, the agent only sees the merged, ranked result.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from allegro_mcp.models.deep_search import DeepSearchResult, SearchPath
from allegro_mcp.models.offer import OfferSummary
from allegro_mcp.models.search import SearchResult
from allegro_mcp.tools._parsers import parse_search_result
from allegro_mcp.utils.polish_text import (
    fold_diacritics,
    lightweight_stem,
    looks_like_ean,
    tokenise,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from allegro_mcp.client import AllegroClient
    from allegro_mcp.tools import ToolContext


_MAX_OFFERS_RETURNED = 40


def register(mcp: FastMCP, context: ToolContext) -> None:
    """Attach `deep_search` and `expand_search`."""

    @mcp.tool
    async def deep_search(
        phrase: Annotated[str, Field(description="Search query, free text")],
        hints: Annotated[
            dict[str, str] | None,
            Field(
                description=(
                    "Optional hints: `category_id`, `brand`, `mpn`, `ean`. "
                    "Each one steers an additional parallel branch."
                )
            ),
        ] = None,
        budget_seconds: Annotated[
            float,
            Field(
                ge=1.0,
                le=30.0,
                description="Soft time budget; branches running longer are abandoned",
            ),
        ] = 8.0,
    ) -> DeepSearchResult:
        """Fan out a search across multiple branches and return merged results.

        Use this when a single `search_offers` would be unreliable: ambiguous
        phrasing, possible barcode input, brand+model lookup, missing
        diacritics, or when results may differ across the Polish, Czech and
        Slovak Allegro marketplaces. Do not use it as a default — its
        latency budget is multiple seconds. For a simple query with a clear
        phrase, `search_offers` is faster.
        """
        return await _deep_search(
            client=context.client,
            phrase=phrase,
            hints=dict(hints or {}),
            budget_seconds=budget_seconds,
        )

    @mcp.tool
    async def expand_search(
        phrase: Annotated[str, Field(description="The phrase whose initial search was too narrow")],
        prior_results_count: Annotated[int, Field(ge=0)] = 0,
    ) -> SearchResult:
        """Broaden a search progressively when initial results are too few.

        Use this only after a `search_offers` call returned fewer matches
        than the agent expected. The tool drops filters in stages, tries
        diacritic-folded and stemmed variants, and reports what it relaxed.
        Do not use this as the first lookup — it is a fallback strategy.
        """
        return await _expand_search(
            client=context.client,
            phrase=phrase,
            prior_results_count=prior_results_count,
        )


async def _deep_search(
    *,
    client: AllegroClient,
    phrase: str,
    hints: dict[str, str],
    budget_seconds: float,
) -> DeepSearchResult:
    branches: list[tuple[str, dict[str, Any], Callable[[], Awaitable[Any]]]] = []

    def add(name: str, params: dict[str, Any]) -> None:
        async def call() -> Any:
            return await client.get("/offers/listing", params=params)

        branches.append((name, params, call))

    add("phrase", {"phrase": phrase, "limit": 24})

    folded = fold_diacritics(phrase)
    if folded != phrase:
        add("phrase_folded", {"phrase": folded, "limit": 24})

    if "category_id" in hints:
        add(
            "phrase_in_category",
            {"phrase": phrase, "category.id": hints["category_id"], "limit": 24},
        )

    if "brand" in hints:
        add(
            "brand_query",
            {"phrase": f"{hints['brand']} {phrase}".strip(), "limit": 24},
        )

    if "mpn" in hints:
        add("mpn_query", {"phrase": hints["mpn"], "limit": 24})

    if "ean" in hints or looks_like_ean(phrase):
        ean = hints.get("ean") or phrase.strip().replace(" ", "").replace("-", "")
        add("ean_query", {"phrase": ean, "limit": 24})

    add(
        "archive",
        {"phrase": phrase, "publication.endingFrom": "-90d", "limit": 24},
    )

    results = await _run_branches(branches, budget_seconds=budget_seconds)

    merged: dict[str, OfferSummary] = {}
    paths_taken: list[SearchPath] = []
    for name, params, payload, elapsed_ms, error in results:
        path = SearchPath(
            name=name,
            query={k: v for k, v in params.items() if v is not None},
            elapsed_ms=elapsed_ms,
            error=error,
        )
        if payload is not None:
            parsed = parse_search_result(payload)
            path.result_count = len(parsed.offers)
            for offer in parsed.offers:
                key = offer.product_id or offer.offer_id
                if key in merged:
                    continue
                merged[key] = offer
        paths_taken.append(path)

    ranked = sorted(merged.values(), key=_rank_offer)
    truncated = len(ranked) > _MAX_OFFERS_RETURNED
    return DeepSearchResult(
        phrase=phrase,
        offers=ranked[:_MAX_OFFERS_RETURNED],
        paths_taken=paths_taken,
        total_unique_offers=len(merged),
        total_unique_products=len({o.product_id for o in merged.values() if o.product_id}),
        truncated=truncated,
    )


async def _expand_search(
    *,
    client: AllegroClient,
    phrase: str,
    prior_results_count: int,
) -> SearchResult:
    tokens = tokenise(phrase)
    relaxations: list[tuple[str, str]] = [("original phrase", phrase)]
    folded = fold_diacritics(phrase)
    if folded != phrase:
        relaxations.append(("diacritics folded", folded))
    if len(tokens) >= 2:
        stemmed = " ".join(lightweight_stem(t) for t in tokens)
        relaxations.append(("token stems", stemmed))
        relaxations.append(("dropped last token", " ".join(tokens[:-1])))
    if len(tokens) >= 3:
        relaxations.append(("first two tokens only", " ".join(tokens[:2])))

    notes: list[str] = [
        f"prior result count was {prior_results_count}; trying broader queries",
    ]
    best: SearchResult | None = None
    for label, candidate in relaxations:
        payload = await client.get(
            "/offers/listing",
            params={"phrase": candidate, "limit": 24},
        )
        result = parse_search_result(payload, offset=0, limit=24)
        notes.append(f"{label!r} -> {len(result.offers)} offers")
        if len(result.offers) > (best.total_count if best else 0):
            best = result
            best.notes = list(notes)
            best.sort = "relevance"
        if best and best.total_count >= 5:
            break

    if best is None:
        empty = SearchResult(total_count=0, offers=[], offset=0, limit=0)
        empty.notes = notes
        return empty
    return best


async def _run_branches(
    branches: list[tuple[str, dict[str, Any], Callable[[], Awaitable[Any]]]],
    *,
    budget_seconds: float,
) -> list[tuple[str, dict[str, Any], Any, int, str | None]]:
    started_at = time.monotonic()

    async def _wrapped(
        name: str, params: dict[str, Any], call: Callable[[], Awaitable[Any]]
    ) -> tuple[str, dict[str, Any], Any, int, str | None]:
        t0 = time.monotonic()
        try:
            payload = await call()
            elapsed = int((time.monotonic() - t0) * 1000)
            return name, params, payload, elapsed, None
        except Exception as exc:  # noqa: BLE001 — record the branch failure
            elapsed = int((time.monotonic() - t0) * 1000)
            return name, params, None, elapsed, str(exc)

    tasks = [asyncio.create_task(_wrapped(name, params, call)) for name, params, call in branches]
    try:
        done, pending = await asyncio.wait(tasks, timeout=budget_seconds)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        raise
    results: list[tuple[str, dict[str, Any], Any, int, str | None]] = []
    for task in done:
        results.append(task.result())
    for task in pending:
        task.cancel()
        # Pull a placeholder result for the cancelled branch.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
    if not results:
        return []
    # Sort to match the input order so callers see a stable view.
    order = {name: idx for idx, (name, _, _) in enumerate(branches)}
    results.sort(key=lambda row: order.get(row[0], 999))
    _ = started_at  # retained for potential future budget metrics
    return results


def _rank_offer(offer: OfferSummary) -> tuple[float, float]:
    promoted_penalty = 0.0
    price = offer.price.amount if offer.price else 0.0
    return promoted_penalty, price
