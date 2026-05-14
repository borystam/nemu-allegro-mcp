# Live testing guide

This file is a punch list for whoever runs `allegro-mcp` against the live
Allegro sandbox for the first time. It records what is well-tested, what
is best-effort, and the order in which to validate.

## Preconditions

1. A sandbox application at `apps.developer.allegro.pl/sandbox` with the
   eight scopes listed in [DEVICE_FLOW.md](DEVICE_FLOW.md).
2. `.env` populated with `ALLEGRO_CLIENT_ID`, `ALLEGRO_CLIENT_SECRET`,
   `ALLEGRO_USER_AGENT`, `ALLEGRO_ENVIRONMENT=sandbox`.
3. `uv sync --extra dev` succeeds.
4. `uv run python -m scripts.bootstrap_auth` completes the device flow.

## Confidence per tool

The tools below are roughly grouped by how confident I am that the
upstream endpoint URL, request shape, and response parser match the
real Allegro behaviour. Start with the high-confidence ones; report
back on the rest so I can iterate.

### High confidence

These map to documented public endpoints with well-known shapes:

- `get_my_account` — `GET /me`
- `list_categories` — `GET /sale/categories`
- `get_category_parameters` — `GET /sale/categories/{id}/parameters`
- `search_offers` — `GET /offers/listing`
- `search_archive` — same endpoint with `publication.endingFrom`
- `get_offer` — `GET /sale/product-offers/{id}`
- `search_products` — `GET /sale/products`
- `get_product` — `GET /sale/products/{id}`
- `list_offers_for_product` — `GET /offers/listing?product.id=...`

### Medium confidence

Endpoint or shape is plausibly correct but not personally verified:

- `get_seller` — `GET /users/{id}`. Allegro exposes seller info but the
  exact URL pattern and which subset of fields appear can vary.
- `list_seller_offers` — `GET /offers/listing?seller.id=...`. Filter
  parameter name might be `seller.login` instead of `seller.id` on some
  endpoints.
- `compute_total_cost` — `GET /sale/product-offers/{id}/delivery-methods`
  with `deliveryAddress.postCode` query. The endpoint may be named
  `delivery-cost`, `delivery-quotes`, or similar — verify and adjust the
  parser if so.
- `list_purchases` / `get_purchase` — `/order/checkout-forms`. Shape is
  fairly complex; the parser handles the common fields but rarer fields
  (delivery tracking numbers, refunds) are left in raw parameters.
- `find_pickup_points` — `/order/pickup-points`. The query parameter
  spelling (`postCode` vs `postalCode`) is one place I might be off.

### Lower confidence — please prioritise testing

These are buyer-side endpoints whose exact contract I do not have
in front of me; treat the parsers as a starting point and report back
the actual response shapes:

- `list_messages` / `send_message` — `/messaging/threads` and
  `/messaging/threads/{id}/messages`. Field names for the author and
  attachments may differ.
- `list_bids` / `place_bid` — `/bidding/bids` and
  `PUT /bidding/offers/{id}/bid` with `{"maxAmount": {...}}`.
- `submit_rating` / `list_my_ratings` — `/sale/user-ratings`. Body shape
  for submission is a guess.
- `list_disputes` / `get_dispute` / `open_dispute` — `/sale/disputes`.
  The dispute creation body is a guess.

## Recommended testing order

1. **Read-only public tools.** `get_my_account`, `list_categories`, then
   `search_offers` with a known-good phrase like `iphone 15`. These
   exercise auth, the rate limiter, the parser, and the transport in one
   pass.
2. **Offer detail and product detail.** Pick an offer ID and product ID
   from step 1 and call `get_offer` and `get_product`. Verify that the
   parser doesn't crash on real responses (it should produce a Pydantic
   model with most fields populated).
3. **Comparison and intel.** Take 2–3 offer IDs from step 1 and call
   `compare_offers`, `detect_suspicious`, `seller_trust_signal`. None of
   these need user-scoped permissions beyond the read scopes.
4. **Purchases.** Exercises the `allegro:api:orders:read` scope.
   `POST /internal/snapshot-offers` (with a hand-picked offer-id list)
   verifies the price-history pipeline against the same scope used in
   `get_offer`.
5. **Messaging and ratings.** Read-only first (`list_messages`,
   `list_my_ratings`). Only attempt `send_message` and `submit_rating`
   against orders the user wants to interact with — these have visible
   side effects.
6. **Bidding.** Confirm `list_bids` first. **Do not** call `place_bid`
   on a real auction unless you have an actual intent to bid; bids are
   legally binding.
7. **Disputes.** `list_disputes` and `get_dispute` are safe;
   `open_dispute` should only fire on an order you genuinely want to
   escalate.

## What to report back

For each tool you exercise, capture:

- The HTTP method and path actually called.
- Whether the response parsed cleanly into the Pydantic model (any
  `ValidationError`s).
- The `Trace-Id` from any failure.

The smoke-test script does this automatically for the safe subset:

```bash
uv run python scripts/smoke_test.py http://127.0.0.1:8765/mcp
```

Send me the full stdout and I'll iterate.

## Known assumptions worth re-checking

- **Authentication endpoints.** `https://allegro.pl/auth/oauth/device`
  and `/token` are the production hosts. The sandbox uses
  `https://allegro.pl.allegrosandbox.pl/auth/oauth/...`. Both are
  encoded in `Settings.device_authorization_endpoint`.
- **Accept header.** We send
  `Accept: application/vnd.allegro.public.v1+json`. A few endpoints
  prefer `application/vnd.allegro.beta.v1+json`; tools that rely on
  beta endpoints would need a per-call override.
- **Locale.** We send `Accept-Language: pl-PL`. If the responses are
  English on some endpoints, that's because Allegro doesn't translate
  everything; the `_pl` fields in our models preserve the Polish
  original.
- **Rate limit.** Defaults to 60 rps with a burst of 100; Allegro's
  per-user leaky bucket is documented at ~9000 requests per minute, so
  we sit well below that. `deep_search` issues 4–7 parallel branches.
- **Refresh tokens rotate.** After each refresh the new refresh token
  is persisted. Watch for `invalid_grant` in logs and run
  `scripts/bootstrap_auth.py` again if you see it.
