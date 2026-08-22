-- ashare trading schema
CREATE TABLE IF NOT EXISTS picks (
    id              BIGSERIAL PRIMARY KEY,
    as_of           DATE NOT NULL,
    strategy        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    score           DOUBLE PRECISION,
    weight          DOUBLE PRECISION,
    reason          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_picks_as_of ON picks (as_of DESC);

CREATE TABLE IF NOT EXISTS orders (
    id              BIGSERIAL PRIMARY KEY,
    client_order_id TEXT UNIQUE,
    broker_mode     TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    quantity        INTEGER NOT NULL,
    price           DOUBLE PRECISION,
    status          TEXT NOT NULL DEFAULT 'pending',
    broker_order_id TEXT,
    reason          TEXT,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fills (
    id              BIGSERIAL PRIMARY KEY,
    order_id        BIGINT REFERENCES orders(id),
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    quantity        INTEGER NOT NULL,
    price           DOUBLE PRECISION NOT NULL,
    fee             DOUBLE PRECISION DEFAULT 0,
    broker_mode     TEXT NOT NULL,
    traded_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS positions_snapshot (
    id              BIGSERIAL PRIMARY KEY,
    broker_mode     TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    shares          INTEGER NOT NULL,
    available       INTEGER NOT NULL DEFAULT 0,
    cost_price      DOUBLE PRECISION NOT NULL DEFAULT 0,
    market_value    DOUBLE PRECISION,
    as_of           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS account_snapshot (
    id              BIGSERIAL PRIMARY KEY,
    broker_mode     TEXT NOT NULL,
    cash            DOUBLE PRECISION NOT NULL,
    equity          DOUBLE PRECISION NOT NULL,
    raw_json        JSONB,
    as_of           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
