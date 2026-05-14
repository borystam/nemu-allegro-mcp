# Architecture

This document explains the design choices behind allegro-mcp, focusing on
the parts most likely to surprise a contributor or operator.

## Token isolation

The LLM agent never touches Allegro credentials. The MCP holds the refresh
token on disk in `~/.allegro-mcp/tokens.db` (mode `0600`, parent directory
mode `0700`), exchanges it for short-lived access tokens, caches them in
memory, and injects them per request inside the MCP process. Bearer tokens
never appear in tool responses, log lines, or MCP transport frames the
agent can observe.

Refresh tokens rotate: every successful refresh returns a new refresh
token, and the store is updated atomically. If a refresh fails with
`invalid_grant` the user is asked to re-run `scripts/bootstrap_auth.py`
rather than the server silently entering an unauthenticated state.

## Rate limiting

Allegro enforces a per-user leaky-bucket limit on its REST API. We shape
our outbound traffic with a client-side token bucket whose default rate is
60 req/s with a burst capacity of 100. The defaults are conservative
enough to keep `deep_search` (which fans out 4–7 parallel branches) inside
Allegro's published limits while still letting the server handle one
agent's chatter comfortably.

Retry policy:

- HTTP 429 honours `Retry-After` when present, otherwise falls back to
  the same exponential schedule as 5xx.
- HTTP 5xx retries three times with delays of 250 ms, 1 s, and 4 s.
- HTTP 401 triggers exactly one refresh-and-retry. A second 401 surfaces
  to the caller with the `Trace-Id` for debugging.

## Why deep_search exists

Smaller open-weight models (Qwen 2.5, Llama 3.2 8B, etc.) lose accuracy
once they need to plan more than four or five tool calls. Three of the
most common buyer flows — "find this product across the marketplaces I
have access to," "is there a cheaper seller with comparable quality,"
"this listing looks suspicious, why?" — naturally require five-to-eight
hops if each Allegro endpoint is a separate tool. We fan those out inside
a single MCP tool. The agent sees one tool that takes a phrase and
optional hints and returns the merged, deduplicated, ranked result plus a
`paths_taken` log it can show the user.

`expand_search` is the same pattern applied to a single dimension —
broadening one query progressively until either the result count crosses
a threshold or every strategy has been tried.

## Why no payment execution

The public Allegro REST API does not expose a payment endpoint. Sellers
build offers, buyers add to cart and check out through the Allegro web
and mobile clients, and Allegro's own payment processor (PayU and friends)
handles the funds movement. This is not a policy decision we made — it is
a property of the platform's API surface. `prepare_purchase` therefore
returns a web URL and an app deep link; the user completes the actual
transaction outside the MCP.

This boundary is also a useful safety property: an agent that has been
prompt-injected cannot drain the user's bank account, because the closest
it can get is `place_bid` (which is itself gated on explicit confirmation
and only applies to auction-style listings).

## Module loader

`server.py` reads `ALLEGRO_MCP_MODULES`, defaults to the buy-side set,
and dynamically imports each module via `allegro_mcp.tools.load_module`.
Every module exposes a `register(mcp, context)` function. To add a
sell-side module:

1. Create `src/allegro_mcp/tools/selling.py` exposing `register(mcp, ctx)`.
2. Append `selling` to `ALLEGRO_MCP_MODULES`.
3. Restart the MCP.

The core HTTP client, token manager, and rate limiter already gate
outbound requests, so a new module only has to translate between Allegro
endpoints and Pydantic models.

## Persistence

Two SQLite databases live under `~/.allegro-mcp/`:

- `tokens.db` — single-row token cache, schema in
  `src/allegro_mcp/auth/token_store.py`.
- `history.db` — price snapshots, schema in
  `src/allegro_mcp/persistence/schema.sql`.

There is no built-in scheduler in v1. The server exposes
`POST /internal/poll-watched` (authenticated by
`ALLEGRO_INTERNAL_SECRET`) which iterates the watched offers and writes a
snapshot per offer. Operators wire this to cron, systemd timers, or an
external orchestrator. The endpoint is intentionally narrow — it is the
only side effect on the history database — and it is bound to the same
internal address as the MCP transport, so exposing it externally requires
explicit reverse-proxy configuration.

## Pydantic returns, not raw dicts

Every tool returns a Pydantic model. We translate Polish field names from
Allegro responses into English keys at the parser layer, preserving the
original Polish in `_pl` fields where it adds value (notably category
names). This gives the agent stable, documented JSON shapes regardless of
incremental Allegro field renames.
