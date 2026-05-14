# Deployment

allegro-mcp is a single Python process that exposes the MCP over
streamable HTTP. Choose the deployment model that matches your platform.

## Configuration reference

All settings are environment variables. The defaults are sensible for a
single-user, single-host deployment.

| Variable | Required | Default | Notes |
|---|---|---|---|
| `ALLEGRO_CLIENT_ID` | yes | — | From apps.developer.allegro.pl |
| `ALLEGRO_CLIENT_SECRET` | yes | — | Same |
| `ALLEGRO_USER_AGENT` | yes | — | E.g. `allegro-mcp/0.2 (you@example.com)`. Allegro's REST API terms (art. 3.4(c)) require an honest, attributable user agent. |
| `ALLEGRO_ENVIRONMENT` | no | `production` | `production` or `sandbox` |
| `ALLEGRO_TOKEN_DB_PATH` | no | `~/.allegro-mcp/tokens.db` | Created 0600 in a 0700 parent |
| `ALLEGRO_HISTORY_DB_PATH` | no | `~/.allegro-mcp/history.db` | Price snapshots |
| `ALLEGRO_MCP_PORT` | no | `8765` | Streamable-HTTP port |
| `ALLEGRO_MCP_BIND` | no | `127.0.0.1` | Bind address; keep on loopback for personal deployments |
| `ALLEGRO_MCP_BEARER` | no | — | If set, every MCP request must carry `Authorization: Bearer <value>`. `/internal/*` routes are exempt (they have their own `X-Internal-Secret` gate). |
| `ALLEGRO_MCP_MODULES` | no | all buy-side | Comma-separated module list; the extension point |
| `ALLEGRO_DEFAULT_POSTAL_CODE` | no | — | Used by `compute_total_cost` |
| `ALLEGRO_RATE_LIMIT_RPS` | no | `60` | Client-side request budget |
| `ALLEGRO_RATE_LIMIT_BURST` | no | `100` | Token bucket capacity |
| `ALLEGRO_INTERNAL_SECRET` | no | — | If set, `/internal/snapshot-offers` is enabled and authenticated by this value |

## systemd

`/etc/systemd/system/allegro-mcp.service`:

```ini
[Unit]
Description=Allegro buy-side MCP server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=allegro-mcp
WorkingDirectory=/opt/allegro-mcp
EnvironmentFile=/etc/allegro-mcp/env
ExecStart=/opt/allegro-mcp/.venv/bin/python -m allegro_mcp
Restart=on-failure
RestartSec=5

# Hardening
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/var/lib/allegro-mcp
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes

[Install]
WantedBy=multi-user.target
```

Then a `/etc/systemd/system/allegro-mcp-snapshot.timer` plus a matching
`.service` unit can drive `/internal/snapshot-offers` on an interval.
Maintain `/etc/allegro-mcp/offers.json` with the list of offer IDs you
want tracked historically (the MCP cannot fetch this from Allegro —
the public API does not expose the user's watch list):

```ini
# allegro-mcp-snapshot.service
[Unit]
Description=Snapshot price history for tracked offers
After=allegro-mcp.service

[Service]
Type=oneshot
ExecStart=/usr/bin/curl -fsS -X POST \
    -H "X-Internal-Secret: ${ALLEGRO_INTERNAL_SECRET}" \
    -H "Content-Type: application/json" \
    --data-binary @/etc/allegro-mcp/offers.json \
    http://127.0.0.1:8765/internal/snapshot-offers
EnvironmentFile=/etc/allegro-mcp/env
```

```ini
# allegro-mcp-snapshot.timer
[Unit]
Description=Periodic price snapshot of tracked offers

[Timer]
OnBootSec=10min
OnUnitActiveSec=4h
Persistent=true

[Install]
WantedBy=timers.target
```

`offers.json` looks like:

```json
{ "offer_ids": ["10000000001", "10000000002"] }
```

## Docker

Multi-stage build keeps the image small:

```dockerfile
FROM python:3.12-slim AS build
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev
COPY src/ ./src/
RUN uv pip install --no-deps -e .

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 allegro
WORKDIR /home/allegro/app
COPY --from=build /app /home/allegro/app
ENV PATH=/home/allegro/app/.venv/bin:$PATH \
    ALLEGRO_TOKEN_DB_PATH=/home/allegro/state/tokens.db \
    ALLEGRO_HISTORY_DB_PATH=/home/allegro/state/history.db
USER allegro
VOLUME ["/home/allegro/state"]
EXPOSE 8765
CMD ["python", "-m", "allegro_mcp"]
```

The first time the container starts, mount a writable volume for state
and run the bootstrap script inside it:

```bash
docker volume create allegro-mcp-state
docker run --rm -it \
    -v allegro-mcp-state:/home/allegro/state \
    --env-file .env \
    allegro-mcp \
    python -m scripts.bootstrap_auth
```

## Authenticating the MCP transport

The MCP HTTP transport accepts every reachable caller by default. Three
strategies are supported, in increasing order of operational cost:

1. **Built-in bearer (recommended for most homelab setups).** Set
   `ALLEGRO_MCP_BEARER` to a long random secret. Every MCP request
   must then carry `Authorization: Bearer <secret>`. Constant-time
   comparison; rotation requires a restart. The `/internal/*` routes
   are exempt because they have their own `X-Internal-Secret` gate.

   ```bash
   ALLEGRO_MCP_BEARER=$(openssl rand -hex 32) \
       op run --env-file=/etc/allegro-mcp/op.env -- \
       python -m allegro_mcp
   ```

   The MCP logs a warning at startup if `ALLEGRO_MCP_BIND` is not
   loopback and `ALLEGRO_MCP_BEARER` is unset, since that combination
   exposes write tools (`place_bid`, `send_message`, `open_dispute`,
   `submit_rating`) to the network.

2. **Loopback only.** The default `ALLEGRO_MCP_BIND=127.0.0.1` is
   sufficient for a single-user laptop or a host that runs both the
   MCP and the agent locally. No external configuration needed.

3. **Reverse proxy (Caddy, nginx, traefik).** Useful when you also
   need TLS termination, request logging, or rate limiting at the
   edge. The bearer header check below is redundant with strategy 1
   but harmless when both are configured.

Caddy:

```
mcp.your-domain.example {
    @authed {
        header Authorization "Bearer secret-token-here"
    }
    reverse_proxy @authed 127.0.0.1:8765
    respond 401
}
```

nginx:

```
server {
    listen 443 ssl http2;
    server_name mcp.your-domain.example;

    location / {
        if ($http_authorization != "Bearer secret-token-here") {
            return 401;
        }
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 5m;
        proxy_set_header Connection "";
    }
}
```

Treat the proxy bearer token as a per-agent credential separate from
your Allegro tokens.

## 1Password CLI

If you keep client credentials in 1Password, inject them at process
start with `op run`:

```
# /etc/allegro-mcp/op.env
ALLEGRO_CLIENT_ID = op://Private/allegro-mcp/client_id
ALLEGRO_CLIENT_SECRET = op://Private/allegro-mcp/client_secret
ALLEGRO_USER_AGENT = allegro-mcp/0.1 (you@example.com)
```

```
op run --env-file=/etc/allegro-mcp/op.env -- python -m allegro_mcp
```

This avoids ever materialising the secrets on disk. The same pattern
works for the bootstrap script:

```
op run --env-file=/etc/allegro-mcp/op.env -- python -m scripts.bootstrap_auth
```

## Sandbox vs production

Switch with `ALLEGRO_ENVIRONMENT`. Keep two separate state directories
so the sandbox tokens are not silently used against production:

```
ALLEGRO_ENVIRONMENT=sandbox
ALLEGRO_TOKEN_DB_PATH=/var/lib/allegro-mcp/sandbox/tokens.db
ALLEGRO_HISTORY_DB_PATH=/var/lib/allegro-mcp/sandbox/history.db
```

The sandbox URLs are
`https://api.allegro.pl.allegrosandbox.pl` and
`https://allegro.pl.allegrosandbox.pl`; production is `https://api.allegro.pl`
and `https://allegro.pl`. The MCP picks the right pair automatically from
the `ALLEGRO_ENVIRONMENT` value.
