-- Additive news tables. Do not drop existing trading/research tables.
CREATE TABLE IF NOT EXISTS news (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    source_id       TEXT,
    url             TEXT,
    title           TEXT NOT NULL,
    content         TEXT,
    summary         TEXT,
    published_at    TIMESTAMPTZ,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    author          TEXT,
    category        TEXT,
    language        TEXT DEFAULT 'zh',
    media           TEXT,
    title_hash      TEXT,
    raw_payload     JSONB
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_title_hash ON news (title_hash);

CREATE TABLE IF NOT EXISTS news_entities (
    id              BIGSERIAL PRIMARY KEY,
    news_id         TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    symbol          TEXT,
    name            TEXT,
    confidence      DOUBLE PRECISION,
    link_source     TEXT
);
CREATE INDEX IF NOT EXISTS idx_news_entities_symbol ON news_entities (symbol);

CREATE TABLE IF NOT EXISTS news_events (
    event_id        TEXT PRIMARY KEY,
    news_id         TEXT,
    symbol          TEXT,
    event_type      TEXT NOT NULL,
    title           TEXT,
    description     TEXT,
    event_time      TIMESTAMPTZ,
    discovery_time  TIMESTAMPTZ,
    source          TEXT,
    source_url      TEXT,
    direction       TEXT,
    direction_score DOUBLE PRECISION,
    impact_score    DOUBLE PRECISION,
    confidence      DOUBLE PRECISION,
    time_horizon    TEXT,
    expectation_gap DOUBLE PRECISION,
    expectation_available BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS news_provider_runs (
    id              BIGSERIAL PRIMARY KEY,
    provider        TEXT NOT NULL,
    status          TEXT NOT NULL,
    symbol          TEXT,
    n_fetched       INTEGER DEFAULT 0,
    error           TEXT,
    ran_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
