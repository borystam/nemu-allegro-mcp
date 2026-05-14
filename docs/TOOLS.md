# Tool reference

Every tool returns a Pydantic model serialised to JSON. The schemas are
embedded in the MCP tool listing; this document is the human-readable
counterpart, focused on when each tool is and is not the right choice.

## Search and discovery

### search_offers(phrase, ...) → SearchResult
Single-shot phrase search via `/offers/listing`. Best when you have a
clear query. Do not use for barcode lookups (`search_products` with
`ean`) or when the initial search returns too few results
(`expand_search`).

### search_archive(phrase, days_back) → SearchResult
Returns ended (closed) offers — useful as a price reference. Do not use
to recommend a purchase; the offers have already ended.

### deep_search(phrase, hints?, budget_seconds) → DeepSearchResult
Parallel fan-out across phrase, diacritic-folded phrase, EAN, MPN,
category-restricted variants, and the archive. Returns merged
deduplicated offers and a `paths_taken` log. Use when phrasing is
ambiguous or the result quality of a single call is uncertain.

### expand_search(phrase, prior_results_count) → SearchResult
Broadens a search progressively when the initial call returned too few
results. Drops filters, folds diacritics, stems tokens. Reports what was
relaxed.

### search_products(phrase?, ean?, mode?) → ProductSearchResult
Catalogue lookup. With `ean`, resolves a barcode to a product. Without,
fuzzy-matches the phrase. Do not use when you want active offers; call
`list_offers_for_product` afterwards.

### get_product(product_id) → Product
Canonical product record once you know the ID.

### list_offers_for_product(product_id, sort?) → list[OfferSummary]
All active offers for a specific product, sorted by price by default.

### list_categories(parent_id?) → list[Category]
Walk the category tree, top-level when `parent_id` is omitted.

### get_category_parameters(category_id) → CategoryParameters
Returns the structured filters a category supports. Useful before
crafting a filtered `search_offers`.

### get_offer(offer_id) → Offer
Full detail for one offer. Avoid bulk usage — use `compare_offers`.

### get_seller(seller_id) → Seller
Public seller profile. For a composite trust score with reasoning,
prefer `seller_trust_signal`.

### list_seller_offers(seller_id, phrase?, limit?) → list[OfferSummary]
What a seller is currently listing, optionally filtered by phrase.

## Comparison

### compare_offers(offer_ids, weights?) → ComparisonTable
Side-by-side, ranked. Weights default to
`{price: 0.5, delivery: 0.2, seller_score: 0.2, smart: 0.1}` and are
normalised. The first row is the best by combined score; ties break on
landed cost.

### compute_total_cost(offer_id, delivery_method?, postal_code?, quantity)
Landed cost (price + delivery) for an offer and postcode. Falls back to
offer-level delivery information if no postcode quote is available.

## Intelligence

### detect_suspicious(offer_ids) → list[SuspicionFlag]
Flags: price >3σ below product median (when at least five comparables
exist), seller with fewer than 50 reviews, parameter-vs-title mismatch,
free delivery on near-zero-priced items. The severity is heuristic.

### seller_trust_signal(seller_id) → TrustSignal
Numeric score with reasoning. Bands: high, medium, low. Combines rating,
review count, super-seller status, and business vs private. Always
inspect the `notes` field.

### price_history(offer_id_or_product_id, days) → PriceHistory
Locally-recorded price history from `~/.allegro-mcp/history.db`. Use
this to identify dips and durable price drops. Coverage depends on
the operator wiring `POST /internal/snapshot-offers` to a scheduler
with the list of offer IDs they want tracked. Allegro does not expose
the user's watch list via its public API, so the MCP cannot derive
that list itself.

### find_lower_price(reference_offer_id, max_rating_drop?) → list[OfferSummary]
Cheaper alternative sellers for the same product, subject to a
seller-quality floor (default 5.0, i.e. no floor). Returns up to 20.

## Buyer actions

### list_purchases(period_days, status?) → list[Purchase]
Order history within a window. Use for finding orders to rate or open
disputes against.

### get_purchase(order_id) → Purchase
Full record for a single order.

### list_messages(thread_id?) → list[MessageThread]
Thread index when `thread_id` is omitted; the messages of a single
thread otherwise.

### send_message(thread_id, body) → Message
Post into an existing thread.

### list_bids() → list[Bid]
Active and recent bids for the authenticated account.

### place_bid(offer_id, amount, confirm) → Bid
Place a maximum bid. **Refuses without `confirm=True`.** The agent must
obtain the user's explicit, informed authorisation for the exact amount
on the exact offer before passing the confirmation through.

### submit_rating(order_id, rating, comment?) → Rating
Leave 1–5 stars and optional text for a completed order.

### list_my_ratings(limit) → list[Rating]
Ratings the authenticated buyer has previously submitted.

### list_disputes() → list[Dispute]
All disputes the buyer has opened.

### get_dispute(dispute_id) → Dispute
Full record with messages.

### open_dispute(order_id, reason, description) → Dispute
Open a buyer-protection dispute. Use only after lighter contact (a
message to the seller) has failed.

## Account and handoff

### get_my_account() → Account
The authenticated user's profile.

### prepare_purchase(offer_id, quantity) → PurchaseHandoff
Web URL plus app deep link to complete the purchase. Never calls any
payment endpoint — Allegro does not expose one in the public API.

### find_pickup_points(postal_code, radius_km, providers?) → list[PickupPoint]
Nearby pickup points (lockers, kiosks) for delivery selection.
