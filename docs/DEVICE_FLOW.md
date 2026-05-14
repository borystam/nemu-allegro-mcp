# Device flow

The Allegro public API uses OAuth 2.0. Because allegro-mcp typically runs
on a host without a graphical browser — a personal server, a Raspberry
Pi, a Docker container — we use the **device authorization grant**.

## Register the application

Go to [`apps.developer.allegro.pl`](https://apps.developer.allegro.pl/)
and sign in with the personal Allegro account whose data you want the
MCP to act on.

Click **Zarejestruj nową aplikację** (Register a new application). Fill
the form:

- **Nazwa aplikacji** (Application name): a name only you will see, for
  example `allegro-mcp-private`.
- **Opis** (Description): one line is fine.
- **Typ aplikacji** (Application type): tick the **Aplikacja, w której
  użytkownik nie ma dostępu do przeglądarki** option — the "device flow"
  application type. This unlocks `grant_type=device_code`.
- **Adres URL aplikacji** (Application URL): the URL of this repository
  is acceptable for a private deployment.

In the **Uprawnienia** (Permissions) panel, tick exactly these eight
scopes:

- `allegro:api:profile:read`
- `allegro:api:sale:offers:read`
- `allegro:api:orders:read`
- `allegro:api:payments:read`
- `allegro:api:bids`
- `allegro:api:messaging`
- `allegro:api:disputes`
- `allegro:api:ratings`

Submit. Allegro will display a **Client ID** and a **Client Secret** —
copy them into your `.env` file (`ALLEGRO_CLIENT_ID` and
`ALLEGRO_CLIENT_SECRET`).

## Run the bootstrap script

With the values populated:

```bash
uv run python -m scripts.bootstrap_auth
```

The script prints something like:

```
Open the following URL on any device:
  https://allegro.pl/auth/oauth/device?user_code=ABCD-EFGH
and enter the user code: ABCD-EFGH
The code expires in 600 seconds. This script will poll until you complete the prompt.
```

Open the URL on any device where you can log into Allegro, complete the
confirmation, and the script will receive the tokens, write them to
`~/.allegro-mcp/tokens.db` with mode `0600`, and exit.

## Things that go wrong

**The device code expires before you finish.** Allegro gives you
roughly ten minutes by default. The script exits with a clear message;
re-run it.

**You see `unauthorized_client`.** Either the application type is not
device-flow, or the eight scopes above are not all ticked. Edit the
application at `apps.developer.allegro.pl` and re-run the bootstrap.

**You see `invalid_grant` after a long pause.** The refresh token has
been revoked (manually, by re-registering the app, or by a long period
of inactivity). Run `uv run python -m scripts.revoke_tokens` to clean up
local state, then bootstrap again.

## Sandbox

Set `ALLEGRO_ENVIRONMENT=sandbox` and the bootstrap script will target
`allegro.pl.allegrosandbox.pl`. Register a separate application on the
sandbox developer portal — sandbox and production credentials are
distinct. The eight scopes are still required.

## Revoking access

`scripts/revoke_tokens.py` revokes both the access token and the refresh
token on Allegro's side and clears the local database. You can also
revoke from the Allegro web UI under your account settings. After either
path, re-running the bootstrap script is the only way to restore service.
