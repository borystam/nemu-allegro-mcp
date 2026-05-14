-- Price history persistence schema.
-- Each row is one observation; coordinated by (offer_id, captured_at).

CREATE TABLE IF NOT EXISTS price_snapshots (
    offer_id TEXT NOT NULL,
    product_id TEXT,
    price_amount REAL NOT NULL,
    currency TEXT NOT NULL,
    captured_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    seller_id TEXT,
    stock_available INTEGER,
    PRIMARY KEY (offer_id, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_offer
    ON price_snapshots(offer_id, captured_at DESC);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_product
    ON price_snapshots(product_id, captured_at DESC);
