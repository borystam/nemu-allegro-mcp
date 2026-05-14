# allegro-mcp

A Model Context Protocol server that exposes Allegro's buy-side REST API to
LLM agents. The server is optimised for search, comparison, and due
diligence on listings before a human completes the purchase. The agent
talks to the MCP; the MCP talks to Allegro; Allegro credentials never reach
the agent.

Allegro's public REST API does not expose payment endpoints, so the MCP
never completes a transaction. Instead, `prepare_purchase` returns a web
URL and an app deep link that hand the user back to Allegro to finish
checkout.

## Feature summary

- Search and discovery, including a fan-out `deep_search` and a
  `expand_search` fallback for narrow queries.
- Side-by-side `compare_offers` with weighted ranking and landed-cost
  calculation.
- Intelligence: suspicion flags, composite seller-trust scores, and local
  price history.
- Buyer actions: watch list, purchase history, seller messaging, auction
  bidding (guarded by explicit confirmation), ratings, disputes, pickup
  points.
- Persistent SQLite stores for OAuth tokens and price history.
- Streamable-HTTP transport, async throughout, rate limiting and retry
  against Allegro's leaky-bucket limits.

## Quickstart

Prerequisites: Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and an
OAuth application registered at
[`apps.developer.allegro.pl`](https://apps.developer.allegro.pl/) with the
eight buy-side scopes listed in [`docs/DEVICE_FLOW.md`](docs/DEVICE_FLOW.md).

```bash
git clone https://github.com/borystam/allegro-agent-mcp.git allegro-mcp
cd allegro-mcp

uv sync --extra dev

cp .env.example .env
# Edit .env with your client id, client secret, and a user-agent string.

uv run python -m scripts.bootstrap_auth
# Open the printed URL, authorise, and the script will store your tokens.

uv run python -m allegro_mcp
# The MCP is now listening on http://127.0.0.1:8765/mcp by default.
```

Smoke-test the running server against the configured environment:

```bash
uv run python scripts/smoke_test.py http://127.0.0.1:8765/mcp
```

## Configuration

All settings come from environment variables, optionally loaded from a
`.env` file. The full table is in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md), but the minimum needed to
start is:

| Variable | Required | Description |
|---|---|---|
| `ALLEGRO_CLIENT_ID` | yes | OAuth client id from apps.developer.allegro.pl |
| `ALLEGRO_CLIENT_SECRET` | yes | OAuth client secret |
| `ALLEGRO_USER_AGENT` | yes | Required by Allegro's REST terms |
| `ALLEGRO_ENVIRONMENT` | no | `production` or `sandbox`; default `production` |

Token and history paths default to `~/.allegro-mcp/tokens.db` and
`~/.allegro-mcp/history.db`. The parent directory is created with mode
`0700` and the token file with mode `0600`.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — design rationale,
  token isolation, rate limit strategy, extensibility.
- [`docs/TOOLS.md`](docs/TOOLS.md) — full tool reference with input and
  output schemas.
- [`docs/DEVICE_FLOW.md`](docs/DEVICE_FLOW.md) — registering the OAuth
  application and running the bootstrap script.
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — systemd, Docker, reverse
  proxy, and secret-injection patterns.
- [`docs/LIVE_TESTING.md`](docs/LIVE_TESTING.md) — a punch list for
  running the server against the live sandbox the first time,
  including a per-tool confidence rating.

## Licence

[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0/),
see [`LICENSE`](LICENSE). You may use, fork, modify, and redistribute the
software for any non-commercial purpose, including personal research and
hobby projects, provided that you retain the copyright notice. Commercial
or corporate use is not permitted under this licence; contact the
copyright holders if you need other terms.
